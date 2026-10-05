import urllib.parse
import os
import boto3, csv, datetime
from datetime import timedelta

# Creo dos clientes de S3. Puedo usar uno solo, pero dejo dos por claridad
# ya que escribo en dos buckets distintos.
s3_1 = boto3.client("s3")
s3_2 = boto3.client("s3")

# Buckets de salida donde voy a dejar el CSV generado con las semanas procesadas
BUCKET_OUT_1 = os.environ["WEEKLY_MONTHLY_BUCKET"]
BUCKET_OUT_2 = os.environ["WEEKLY_ALERTS_BUCKET"]

# Nombre del fichero de salida que voy a sobrescribir cada vez
CSV_SALIDA = "outputSemanas.csv"

# Definimos una funcion para cargar el csv como diccionario, y asi trabajar con el
def cargar_csv_como_dict_local_desde_string(contenido_csv):
    dias = {}

    # Divido el contenido del CSV en líneas y creo un lector CSV a partir de ellas
    lineas = contenido_csv.splitlines()
    reader = csv.DictReader(lineas)

    # Recorro cada fila del CSV y la guardo en mi diccionario
    for row in reader:
        fecha = row["Fecha"]

        dias[fecha] = [
            fecha,
            float(row["Medias"]),
            float(row["Desviaciones"])
        ]

    return dias

# Definimos la funcion para que el diccionario que tenemos se convierta a csv
def convertir_diccionario_a_csv_string(diccionario):

    # Ordeno las filas en orden creciente de fechas
    filas_ordenadas = sorted(
        diccionario.values(),
        key=lambda x: datetime.datetime.strptime(x[0], "%Y/%m/%d")
    )

    # Cabecera del CSV
    csv_str = "Fecha,Medias,Desviaciones\n"

    # Genero cada línea
    for fila in filas_ordenadas:
        csv_str += f"{fila[0]},{fila[1]},{fila[2]}\n"

    return csv_str

# Definimos una funcion que dependiendo de cada fecha, lo agrupe para una semana en funcion de los
# dias a los que afecte
def agrupar_por_semanas(diccionario):
    semanas = {}  # Ej. {"2017/03/20" : [(dias_aportados, [media, desviación]), ...]}

    for fecha_str, datos in diccionario.items():

        # Convierto la fecha de string a objeto datetime
        fecha = datetime.datetime.strptime(fecha_str, "%Y/%m/%d")
        media = datos[1]
        desv = datos[2]

        # weekday: lunes=0, domingo=6
        weekday = fecha.weekday()

        # Calculo el lunes de esa semana
        lunes = fecha - timedelta(days=weekday)
        lunes_str = lunes.strftime("%Y/%m/%d")

        # EJEMPLO: miércoles (weekday = 2) -> aporta 5 días a esta semana (7 - 2)
        dias_semana_actual = 7 - weekday

        # Si la semana aún no existe en el diccionario, la creo
        if lunes_str not in semanas:
            semanas[lunes_str] = []

        # Guardo cuánto aporta este día a su semana
        semanas[lunes_str].append((dias_semana_actual, [media, desv]))

        # Si NO es lunes, también contribuye al dato del lunes de la semana siguiente
        if weekday != 0:
            lunes_sig = lunes + timedelta(days=7)
            lunes_sig_str = lunes_sig.strftime("%Y/%m/%d")

            # EJEMPLO: miércoles -> aporta 2 días (los anteriores) a la semana siguiente
            dias_sem_siguiente = weekday

            if lunes_sig_str not in semanas:
                semanas[lunes_sig_str] = []

            semanas[lunes_sig_str].append((dias_sem_siguiente, [media, desv]))

    # Inicializamos el diccionario donde vamos a añadir los datos para cada semana
    resultado = {}

    for lunes, elementos in semanas.items():

        # Suma total de pesos (días aportados por los valores de la semana)
        total_pesos = sum(e[0] for e in elementos)

        # Media ponderada = sum(peso * valor) / sum(pesos)
        media_def = sum(e[0] * e[1][0] for e in elementos) / total_pesos
        desv_def = sum(e[0] * e[1][1] for e in elementos) / total_pesos

        # La clave es el lunes de la semana y el valor es el registro final
        resultado[lunes] = [lunes, media_def, desv_def]

    return resultado

def lambda_handler(event, context):

    print("Lambda AGRUPACIÓN SEMANAL ejecutada.")

    # Obtengo el bucket y la key del fichero que ha generado el evento
    bucket_in = event["Records"][0]["s3"]["bucket"]["name"]
    key_in = urllib.parse.unquote_plus(event["Records"][0]["s3"]["object"]["key"])

    print(f"Archivo recibido: {bucket_in}/{key_in}")

    # Descargo el CSV directamente desde S3
    respuesta = s3_1.get_object(Bucket=bucket_in, Key=key_in)
    contenido_csv = respuesta["Body"].read().decode("utf-8")

    # Convierto el CSV en mi diccionario de días → medias → desviaciones
    dias = cargar_csv_como_dict_local_desde_string(contenido_csv)

    # Aplico mi lógica exacta de agrupación semanal
    semanas = agrupar_por_semanas(dias)

    # Convierto el diccionario final en un CSV listo para guardar
    csv_final = convertir_diccionario_a_csv_string(semanas)

    # Subo el fichero a mi primer bucket
    s3_1.put_object(
        Bucket=BUCKET_OUT_1,
        Key=CSV_SALIDA,
        Body=csv_final.encode("utf-8")
    )
    print(f"CSV semanal generado en: {BUCKET_OUT_1}/{CSV_SALIDA}")

    # Subo el fichero también al segundo bucket
    s3_2.put_object(
        Bucket=BUCKET_OUT_2,
        Key=CSV_SALIDA,
        Body=csv_final.encode("utf-8")
    )
    print(f"CSV semanal generado en: {BUCKET_OUT_2}/{CSV_SALIDA}")

    # Respuesta final de la Lambda
    return {
        "statusCode": 200,
        "body": "Agrupación semanal generada correctamente (sobrescritura total)."
    }
