"""Offline regression tests: no AWS calls or SNS messages are made."""
import csv
import importlib.util
import io
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
ENV = {'AWS_DEFAULT_REGION': 'us-east-1', 'CLEAN_BUCKET': 'clean',
       'WEEKLY_MONTHLY_BUCKET': 'weekly-monthly', 'WEEKLY_ALERTS_BUCKET': 'weekly-alerts',
       'MONTHLY_BUCKET': 'monthly', 'STATE_BUCKET': 'state', 'SNS_TOPIC_NAME': 'test-alerts'}


class MissingKey(ClientError):
    def __init__(self):
        super().__init__({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')


class MemoryS3:
    exceptions = SimpleNamespace(NoSuchKey=MissingKey)

    def __init__(self):
        self.objects = {}

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise MissingKey()
        return {'Body': io.BytesIO(self.objects[Bucket, Key])}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[Bucket, Key] = Body.encode() if isinstance(Body, str) else Body

    def download_file(self, bucket, key, path):
        Path(path).write_bytes(self.get_object(Bucket=bucket, Key=key)['Body'].read())


def event(bucket, key):
    return {'Records': [{'s3': {'bucket': {'name': bucket}, 'object': {'key': key}}}]}


def load_module(name, path, s3, sns):
    with patch.dict(os.environ, ENV), patch('boto3.client', side_effect=lambda service, **kw: s3 if service == 's3' else sns):
        spec = importlib.util.spec_from_file_location(name, ROOT / path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.s3 = MemoryS3()
        self.sns = Mock()
        self.sns.get_paginator.return_value.paginate.return_value = [
            {'Topics': [{'TopicArn': 'arn:aws:sns:us-east-1:000000000000:test-alerts'}]}]
        self.modules = {name: load_module(name, f'lambdas/{name}.py', self.s3, self.sns)
                        for name in ['deduplicate', 'weekly', 'monthly', 'alerts']}
        self.api = load_module('application', 'api/application.py', self.s3, self.sns)

    def run_pipeline(self):
        self.s3.put_object(Bucket='raw', Key='input.csv', Body=(ROOT/'data/sample_temperatures.csv').read_bytes())
        self.modules['deduplicate'].lambda_handler(event('raw', 'input.csv'), None)
        self.modules['weekly'].lambda_handler(event('clean', 'output_diasDuplicados.csv'), None)
        self.modules['monthly'].lambda_handler(event('weekly-monthly', 'outputSemanas.csv'), None)
        self.modules['alerts'].lambda_handler(event('weekly-alerts', 'outputSemanas.csv'), None)

    def test_pipeline_metrics_and_api(self):
        self.run_pipeline()
        client = self.api.app.test_client()
        expected = {'/temp': ('Temperatura media', 16.0), '/sd': ('Desviacion maxima', 0.7)}
        for route, (field, value) in expected.items():
            result = client.get(route+'?year=2025&month=1')
            self.assertEqual(result.status_code, 200)
            self.assertEqual(float(result.json[field]), value)
        diff = client.get('/maxdiff?year=2025&month=2')
        self.assertEqual(float(diff.json['Diferencia de temperaturas maximas']), 2.0)
        self.assertEqual(self.sns.publish.call_count, 1)

    def test_sequential_replay_does_not_repeat_alert(self):
        self.run_pipeline()
        before = self.s3.objects['monthly', 'datos_procesados.csv']
        self.run_pipeline()
        self.assertEqual(self.s3.objects['monthly', 'datos_procesados.csv'], before)
        self.assertEqual(self.sns.publish.call_count, 1)

    def test_monthly_increment_preserves_typed_prior_rows(self):
        self.run_pipeline()
        self.s3.put_object(Bucket='weekly-monthly', Key='next.csv', Body='Fecha,Medias,Desviaciones\n2025/03/03,21,0.2\n')
        self.modules['monthly'].lambda_handler(event('weekly-monthly', 'next.csv'), None)
        rows = list(csv.DictReader(io.StringIO(self.s3.objects['monthly', 'datos_procesados.csv'].decode())))
        self.assertEqual(len(rows), 3)
        self.assertEqual(float(rows[-1]['diff_temperatura']), 2.0)

    def test_missing_sns_topic_does_not_mark_alert_sent(self):
        self.s3.put_object(Bucket='weekly-alerts', Key='week.csv', Body='Fecha,Medias,Desviaciones\n2025/01/06,15,0.7\n')
        self.sns.get_paginator.return_value.paginate.return_value = [{'Topics': []}]
        with self.assertRaises(RuntimeError):
            self.modules['alerts'].lambda_handler(event('weekly-alerts', 'week.csv'), None)
        self.assertNotIn(('state', 'estado-alertas.csv'), self.s3.objects)
        self.sns.publish.assert_not_called()

    def test_access_denied_does_not_become_empty_state(self):
        error = ClientError({'Error': {'Code': 'AccessDenied'}}, 'GetObject')
        with patch.object(self.s3, 'get_object', side_effect=error):
            with self.assertRaises(ClientError):
                self.modules['alerts'].load_state()
        with patch.object(self.s3, 'download_file', side_effect=error):
            with self.assertRaises(ClientError):
                self.modules['deduplicate'].lambda_handler(event('raw', 'input.csv'), None)

    def test_duplicate_dates_use_new_value(self):
        fn = self.modules['deduplicate'].fusionar_datos
        self.assertEqual(fn({'date': [1]}, {'date': [2]}), {'date': [2]})

    def test_api_validation_and_health(self):
        client = self.api.app.test_client()
        self.assertEqual(client.get('/health').status_code, 200)
        for query in ['', '?year=2025', '?year=x&month=1', '?year=2025&month=13', '?year=2025&month=1&extra=yes']:
            self.assertEqual(client.get('/temp'+query).status_code, 400)
        self.run_pipeline()
        self.assertEqual(client.get('/temp?year=1900&month=1').status_code, 404)

    def test_weekly_weighting(self):
        # Wednesday contributes 5 days to its Monday and 2 to the next Monday.
        result = self.modules['weekly'].agrupar_por_semanas({'2025/01/08': ['2025/01/08', 14, 0.2],
                                                          '2025/01/13': ['2025/01/13', 21, 0.4]})
        self.assertEqual(result['2025/01/06'][1], 14)
        self.assertAlmostEqual(result['2025/01/13'][1], (2*14+7*21)/9)


if __name__ == '__main__':
    unittest.main()
