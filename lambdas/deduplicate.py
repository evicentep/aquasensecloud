from botocore.exceptions import ClientError
import os
import urllib.parse, boto3, csv, datetime # Importamos los paquetes necesarios para usar

s3 = boto3.client('s3') # Definimos nuestro cliente de s3 para acceder a los buckets
BUCKET_OUT = os.environ["CLEAN_BUCKET"] # Escribimos el nombre del bucket de salida donde vamos a almacenar nuestro csv
CSV_KEY_OUT = "output_diasDuplicados.csv" # Escribimos el nombre del csv donde almacenaremos esos datos

# Definiremos una funcion para cargar un csv como un diccionario para tratarlo en local
def cargar_csv_como_dict_local(ruta):
    dias = {}  # Diccionario donde almacenamos las fechas

    with open(ruta, "r", encoding="utf-8") as f: # Abrimos el fichero
        reader = csv.DictReader(f)

        # Para cada fila, obtendremos todos los datos que queremos
        for row in reader:
            fecha = row["Fecha"]
            dias[fecha] = [
                fecha,
                float(row['Medias']),
                float(row["Desviaciones"])
            ]

    return dias # Devolvemos el diccionario con fecha -> (fecha, Media, Desviacion)

# Definimos una funcion para que un diccionario se pueda guardar como un csv
def convertir_diccionario_a_csv_string(diccionario):

    # Ordenamos las fechas para que esten ordenadas en orden creciente para mejor procesamiento
    filas_ordenadas = sorted(
        diccionario.values(),
        key=lambda x: datetime.datetime.strptime(x[0], "%Y/%m/%d")
    )

    # Escribimos la primera fila del csv
    csv_str = "Fecha,Medias,Desviaciones\n"

    # Para cada fila, pasamos esos valores a string
    for fila in filas_ordenadas:
        fecha, media, desv = fila
        csv_str += f"{fecha},{media},{desv}\n"

    return csv_str

# Definimos una función para que dados dos diccionarios, uno antiguo y otro nuevo, si se da el caso de que 
# hay una fecha que coincide en ambos, el diccionario final se quedará solo con los datos de la fecha en el 
# diccionario nuevo
def fusionar_datos(dias_viejos, dias_nuevos):
    resultado = dias_viejos.copy()

    for fecha, datos_new in dias_nuevos.items():
        resultado[fecha] = datos_new  # si existe, reemplaza por el nuevo

    return resultado # Devolvemos el diccionario con las fechas duplicadas eliminadas

# Definimos la funcion lambda 
def lambda_handler(event, context):

    # Obtenemos el bucket y el fichero csv que han ocasionado la activacion de la lambda
    bucket_in = event["Records"][0]["s3"]["bucket"]["name"]
    key_in = urllib.parse.unquote_plus(event["Records"][0]["s3"]["object"]["key"])

    # Mostramos los nombres obtenidos para depuracion
    print(f"Archivo recibido: {key_in} desde bucket {bucket_in}")

    # Definimos la ruta donde vamos a cargar el fichero, y descargamos ese fichero ahí
    ruta_nuevo = "/tmp/input.csv"
    s3.download_file(bucket_in, key_in, ruta_nuevo)

    # Cargamos el nuevo csv y lo convertimos a diccionario para manejarlo
    dias_nuevos = cargar_csv_como_dict_local(ruta_nuevo)
    print(f"Fichero nuevo contiene {len(dias_nuevos)} fechas.")

    # Definimos la ruta donde vamos a descargar el csv que ya teniamos
    ruta_viejo = "/tmp/output.csv"

    try: # Si se puede descargar algun csv del bucket de salida, significa que ya habian fechas
         # previas, por lo que el csv ya existia
        s3.download_file(BUCKET_OUT, CSV_KEY_OUT, ruta_viejo) # Descargamos el fichero en la ruta deseada
        dias_viejos = cargar_csv_como_dict_local(ruta_viejo) # Cargamos el csv a un diccionario local
        print(f"CSV previo cargado: {len(dias_viejos)} fechas.") # Depuramos para ver el csv que ya teniamos
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
            raise
        dias_viejos = {}

    # Fusionamos los datos que ya teniamos antiguos con los nuevos que nos entran
    dias_final = fusionar_datos(dias_viejos, dias_nuevos)

    # Convertimos el diccionario final a string para un csv
    csv_final = convertir_diccionario_a_csv_string(dias_final)

    try: # Cargamos el csv al bucket
        s3.put_object(
            Bucket=BUCKET_OUT,
            Key=CSV_KEY_OUT,
            Body=csv_final.encode("utf-8")
        )
        print(f"[Lambda] CSV actualizado en s3://{BUCKET_OUT}/{CSV_KEY_OUT}")
    except Exception as e: # Lanzamos una excepccion por si no se ha podido subir nada
        print("No se ha podido subir el CSV final:", e)
        return {"statusCode": 500, "body": "Error subiendo CSV final"}

    return { # Devolvemos un status code de 200 para mostrar el fin del procesamiento
        "statusCode": 200,
        "body": f"Proceso completado. Total fechas: {len(dias_final)}"
    }