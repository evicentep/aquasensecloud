from botocore.exceptions import ClientError
import os
import boto3 
import csv 
import json  
import urllib.parse  
from datetime import datetime  
from io import StringIO 

s3 = boto3.client("s3") #Generamos cliente s3 para conectar con bucket de s3
sns = boto3.client("sns")#Generamos cliente sns para poder mandar la notificación de alerta si la desviacion supera el valor de 0.5

#Definimos tanto el bucket que vamos a utilizar para tener el estado de la alerta True o False, para por si se actualiza el fichero de entrada, llevar una cuenta de que alertas hemos enviado ya para no enviarlas

STATE_BUCKET = os.environ["STATE_BUCKET"]  # Nombre del bucket donde se guarda el estado
STATE_KEY = "estado-alertas.csv" #Fichero csv que almacenará el bucket anterior
SNS_TOPIC_NAME = os.environ["SNS_TOPIC_NAME"]  # Nombre del tema de sns


# ------------------------------------------------------
# CARGAMOS EL ESTADO ACTUAL
# ------------------------------------------------------
def load_state():  # Función que carga el estado guardado en S3
    try:
        response = s3.get_object(Bucket=STATE_BUCKET, Key=STATE_KEY) #Obtenemos mediante metodo get_object de s3 el fichero del bucket de s3
        content = response["Body"].read().decode("utf-8")  # Leemos el contenido del fichero como texto

        # Convertimos CSV a un diccionario que seguirá la estructura: { "2023-18": {"deviation":0.43, "alert_sent":False } }, guardaremos aqui para cada desviacion, si se ha enviado o no alerta
        state = {}  # Diccionario donde se almacenará el estado
        reader = csv.DictReader(StringIO(content)) #leemos el fichero csv linea a linea y lo guardamos en reader, que guarda para cada fila un diccionario
        for row in reader:  # Recorremos cada fila del CSV
            week_id = row["week_id"]#accedemos por cada fila a la columna week_id
            state[week_id] = {  # Guardamos la información de esa semana
                "deviation_last_seen": float(row["deviation_last_seen"]), #guardamos el valor de la desviacion
                "alert_sent": row["alert_sent"].lower() == "true"  # Convertimos el valor a booleano
            }

        return state #devuelve el diccionario


    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
            return {}
        raise


# ------------------------------------------------------
# GUARDAMOS ESTADO ACTUALIZADO
# ------------------------------------------------------
def save_state(state_dict):  # Función que guarda el estado actualizado en S3
    output = StringIO()  # Creamos un buffer de texto en memoria
    fieldnames = ["week_id", "deviation_last_seen", "alert_sent"]  # Definimos las columnas del CSV
    writer = csv.DictWriter(output, fieldnames=fieldnames)  # Preparamos el escritor CSV
    writer.writeheader()  # Escribimos la cabecera del fichero

    for week_id, data in state_dict.items():  # Recorremos los datos del estado
        writer.writerow({  # Escribimos cada fila en el CSV
            "week_id": week_id,
            "deviation_last_seen": data["deviation_last_seen"],
            "alert_sent": str(data["alert_sent"]).lower()
        })

    s3.put_object(  # Subimos el fichero generado al bucket de S3
        Bucket=STATE_BUCKET,
        Key=STATE_KEY,
        Body=output.getvalue().encode("utf-8")
    )

# ------------------------------------------------------
# BUSCAMOS ARN DEL SNS POR NOMBRE
# ------------------------------------------------------
def find_sns_topic_arn(topic_name):  # Función que busca el ARN de un topic SNS por su nombre
    for page in sns.get_paginator("list_topics").paginate():
        for topic in page["Topics"]:
            if topic["TopicArn"].endswith(":" + topic_name):
                return topic["TopicArn"]
    return None


# ------------------------------------------------------
# ENVIAR ALERTA A SNS
# ------------------------------------------------------
def send_alert(week_id, deviation):  # Función que envía una alerta al topic SNS
    topic_arn = find_sns_topic_arn(SNS_TOPIC_NAME)  # Buscamos el ARN del topic
    if not topic_arn:  # Si no se encuentra el topic
        print("No se encontró el topic SNS:", SNS_TOPIC_NAME)  # Mostramos mensaje de error
        raise RuntimeError("Configured SNS topic was not found")

    message = f"Alerta: la semana {week_id} supera el umbral de desviación (valor = {deviation})."  # Construimos el mensaje
    sns.publish(  # Publicamos el mensaje en SNS
        TopicArn=topic_arn,
        Message=message,
        Subject="Alerta de desviación semanal"
    )
    print("Alerta enviada:", message)  # Mostramos mensaje de confirmación

# ------------------------------------------------------
# PARSEAMOS CSV SEMANAL RECIÉN SUBIDO
# ------------------------------------------------------
def parse_csv_from_s3(bucket, key):  # Función que lee y procesa el CSV desde S3
    response = s3.get_object(Bucket=bucket, Key=key)  # Descargamos el fichero desde S3
    content = response["Body"].read().decode("utf-8")  # Leemos el contenido como texto

    rows = []  # Lista para guardar los registros procesados
    reader = csv.DictReader(StringIO(content))  # Preparamos el lector CSV

    for row in reader:  # Recorremos cada fila del CSV
        fecha = datetime.strptime(row["Fecha"], "%Y/%m/%d")  # Convertimos la fecha a objeto datetime
        year, week, _ = fecha.isocalendar()  # Obtenemos año y número de semana
        deviation = float(row["Desviaciones"])  # Convertimos la desviación a número

        rows.append({  # Añadimos los datos procesados a la lista
            "week_id": f"{year}-{week}",
            "deviation": deviation
        })

    return rows  # Devolvemos la lista de semanas procesadas


# ------------------------------------------------------
# FUNCIÓN HANDLER PRINCIPAL
# ------------------------------------------------------
def lambda_handler(event, context):  # Función principal que ejecuta la Lambda

    print("Evento recibido:", json.dumps(event, indent=2))  # Mostramos el evento recibido en formato legible

    # 1. Obtenemos bucket y key del CSV procesado por Lambda 2
    bucket = event["Records"][0]["s3"]["bucket"]["name"]  # Extraemos el nombre del bucket
    key = urllib.parse.unquote_plus(event["Records"][0]["s3"]["object"]["key"])  # Obtenemos la ruta del fichero

    print(f"Procesando fichero semanal: s3://{bucket}/{key}")  # Mostramos qué fichero se está procesando

    # 2. Parseamos el CSV subido
    weekly_rows = parse_csv_from_s3(bucket, key)  # Leemos y procesamos el CSV

    # 3. Cargamos estado persistente
    state = load_state()  # Cargamos el estado previo desde S3

    # 4. Procesamos cada semana
    for row in weekly_rows:  # Recorremos cada registro semanal
        week_id = row["week_id"]  # Obtenemos el identificador de semana
        deviation = row["deviation"]  # Obtenemos la desviación actual

        prev = state.get(week_id, {"deviation_last_seen": 0.0, "alert_sent": False})  # Recuperamos el estado previo o uno por defecto

        print(f"→ Semana {week_id}: desviación = {deviation}, antes = {prev}")  # Mostramos información de control

        # REGLA OPCIÓN C:
        # Send once per week identifier; falling below the threshold does not reset it.
        if deviation > 0.5 and prev["alert_sent"] is False:  # Si se supera el umbral por primera vez
            send_alert(week_id, deviation)  # Enviamos la alerta
            prev["alert_sent"] = True  # Marcamos que ya se envió la alerta

        # Actualizamos el valor visto
        prev["deviation_last_seen"] = deviation  # Guardamos la última desviación detectada

        # Guardamos en estado
        state[week_id] = prev  # Actualizamos el estado de esa semana

    # 5. Guardamos estado persistente actualizado
    save_state(state)  # Guardamos el nuevo estado en S3

    print("Lambda completada correctamente.")  # Mensaje final de que todo ha ido bien
    return {"status": "OK", "processed_weeks": len(weekly_rows)}  # Devolvemos el resultado de la ejecución
