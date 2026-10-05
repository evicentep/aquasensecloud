import urllib.parse
import os
import csv
import io
import boto3
from collections import defaultdict

s3 = boto3.client('s3')

def lambda_handler(event, context):

    # ================================
    # 1. LEER CSV DESDE S3
    # ================================
    bucket_entrada = event["Records"][0]["s3"]["bucket"]["name"]
    archivo_entrada = urllib.parse.unquote_plus(event["Records"][0]["s3"]["object"]["key"]) #Fcihero de dentro del bucket donde están los datos por columnas

    obj = s3.get_object(Bucket=bucket_entrada, Key=archivo_entrada) #Creamos objeto de s3 que obtiene el fichero de datos de dentro del bucket indicado
    csv_content = obj['Body'].read().decode('utf-8').splitlines() #Nos quedamos con el body del objeto csv y lo llamamos csv_content

    reader = csv.DictReader(csv_content) #Modulo de CSV que genera diccionarios por cada fila, así luego podemos separar cada fila en una lista con tres elementos separados, que a su vez esas listas se guardan en otra lista que guarda todas las combinaciones de tres elementos de cada fila en items

    items = [row for row in reader] #Generamos una lista que tiene en cada elemento un bloque por cada diccionario guardado en reader

    print(f"Total registros leídos del CSV: {len(items)}")


    # ================================
    # 2. LEER CSV DE SALIDA SI EXISTE
    # ================================
    bucket_salida = os.environ["MONTHLY_BUCKET"] #Este será nuestro bucket de salida que la primera vez no tendrá nada dentro pero las demás si
    archivo_salida = "datos_procesados.csv" #El fichero de dentro del bucket de salida que cogeremos para comparar y ver que elementos añadir/actualizar
    
    #Con el método try, comprobamos si existe el fichero de salida ya o no hay nada dentro del bucket de salida aún
    try:
        obj_salida = s3.get_object(Bucket=bucket_salida, Key=archivo_salida)
        csv_salida_content = obj_salida['Body'].read().decode('utf-8').splitlines()
        reader_salida = csv.DictReader(csv_salida_content)
        resultados_previos = {(int(r["anio"]), int(r["mes"])): {
            "year": int(r["anio"]), "mes": int(r["mes"]),
            "temperatura_media": float(r["temperatura_media"]),
            "temperatura_max": float(r["temperatura_max"]),
            "desviacion_maxima": float(r["desviacion_maxima"]),
            "diff_temperatura": None
        } for r in reader_salida} #El fichero de salida será distinto al de entrada, ya que estará guardado por claves de (año, mes), y a esa clave le asignamos todos los datos que tienen las columnas
        print("CSV de salida existente leído")
    except s3.exceptions.NoSuchKey: #Creamos un diccionario vacío si no encontramos un fichero de salida, donde guardaremos todos los datos que se han recibido del fichero de entrada, por tanto se añadirá todo lo que venga del fichero de entrada a este diccionario vacío
        resultados_previos = {}
        print("CSV de salida no existe, se creará uno nuevo")


    # ================================================
    # 3. AGRUPAR POR AÑO-MES  (temperaturas y desviaciones)
    # ================================================

    #Creamos un diccionario que empieza teniendo dos listas vacías, que contenga para cada par de (año, mes), sus correspondientes 
    grupos = defaultdict(lambda: {
        "temperaturas": [],
        "desviaciones": []
    })

    for item in items:
        fecha = item["Fecha"]
        temperatura = float(item["Medias"])
        desviacion = float(item["Desviaciones"])

        year, mes, dia = map(int, fecha.split("/")) #Pasamos a números enteros y separamos la fecha para tener el año y mes por separado



        # Original coursework rule: assign each weekly record to its start month.
        # Cross-month weighting is not implemented; see docs/ARCHITECTURE.md.


        clave = (year, mes) #La clave será el año junto con el mes, ya que agrupamos por mes no por semana, así si hay varias semanas que coinciden en un mismo mes, se guardan las temperaturas en la misma lista y se les hace media

        grupos[clave]["temperaturas"].append(temperatura)
        grupos[clave]["desviaciones"].append(desviacion)


    # ================================
    # 4. CALCULAR MÉTRICAS POR MES
    # ================================

    #Este apartado, crea un nuevo diccionario, que se comparará con el diccionario que puede ser que venga ya lleno de datos o no, en función de si en el bucket de salida había algo o es la primera vez que se introducen datos

    resultados_nuevos = {}

    #Recogemos los datos en funcion de su clave(año, mes) y sus valores (de momento slo hay lista de temperaturas de ese mes y lista de desviaciones de ese mes)

    for (year, mes), valores in grupos.items():

        temp_media = sum(valores["temperaturas"]) / len(valores["temperaturas"]) #Calculamos la temperatura media para ese mes cogiendo todas las temperaturas
        temp_max = max(valores["temperaturas"])#Calculamos el valor máximo de temperatura
        desviacion_maxima = max(valores["desviaciones"])#Calculamos desviación máxima

        #Este va a ser el diccionario que rellenaremos para cada (año, mes), con todos los valores que queremos introducir, en total serán 6 columnas
        resultados_nuevos[(year, mes)] = {
            "year": year,
            "mes": mes,
            "temperatura_media": temp_media,
            "temperatura_max": temp_max,
            "desviacion_maxima": desviacion_maxima,
            "diff_temperatura": None  # Se calculará luego (ya que si es el primer mes tendrá valor None)
        }


    # ================================
    # 5. ACTUALIZAR O AÑADIR FILAS EN EL CSV SI ES NECESARIO
    # ================================
    resultados_combinados = resultados_previos.copy()  # Resultados de inicio(puede ser vacío si es la primera vez que se inicia)
    resultados_combinados.update(resultados_nuevos)    # Actualizamos los datos con los datos que hemos recogido y procesado del fichero de entrada en resultados_nuevos, si encuentra diferencias respecto a resultados combinados, las actualiza, en el primer caso actualizará todas las filas


    #Ahora que ya hemos actualizado todo, vamos a calcular la columna de diferencia de temperatura
    # ================================
    # 6. ORDENAR Y CALCULAR diff_temperatura
    # ================================
    lista_resultados = list(resultados_combinados.values()) #Nos quedamos con todos los valores de todas las claves
    lista_resultados.sort(key=lambda x: (x["year"], x["mes"])) #Ordenamos por año y mes, de menor a mayor, para ir en orden de tiempo calculando la diferencia de temperatura de mes con mes

    #Empezamos el bucle en 1 ya que no queremos coger el mes 0, porque al hacer i-1 no existiría el mes -1
    for i in range(1, len(lista_resultados)): #Como cada parte de la lista es un mes distinto, recorremos todos los meses
        temp_prev = lista_resultados[i-1]["temperatura_max"] #Obtenemos la temperatura máxima del mes anterior
        temp_curr = lista_resultados[i]["temperatura_max"]#Obtenemos la temperatura máxima del mes actual
        lista_resultados[i]["diff_temperatura"] = temp_curr - temp_prev #Calculamos la diferencia y la añadimos a la lista, correspondiendo a ese mes y la guardamos


    # ================================
    # 7. GENERAR CSV
    # ================================
    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer) #Generamos un escritor de csv donde vamos a copiar los datos

    #Como ya hemos añadido la diferencia, ahora creamos todas las columnas
    writer.writerow([
        "anio",
        "mes",
        "temperatura_media",
        "temperatura_max",
        "desviacion_maxima",
        "diff_temperatura"
    ])
    #Y para cada bloque correspondiente a un mes en la lista de resultados, copiamos todos los valores, y así para todos los elementos de la lista(todos los meses que haya), la lista ya está ordenada entonces añade los datos desde los más antiguos hasta los más nuevos
    for r in lista_resultados:
        writer.writerow([
            r["year"],
            r["mes"],
            r["temperatura_media"],
            r["temperatura_max"],
            r["desviacion_maxima"],
            r["diff_temperatura"]
        ])


    # ================================
    # 8. SUBIR CSV A S3
    # ================================

    #Subiremos los datos en un fichero llamado datos_procesados.csv y a un bucket de destino que se llamará meses-procesados
    bucket_name = bucket_salida
    output_file = "datos_procesados.csv"

    #Subimos el objeto s3
    s3.put_object(
        Bucket=bucket_name,
        Key=output_file,
        Body=csv_buffer.getvalue(),
        ContentType="text/csv"
    )


    #Devuelve que se han realizado todas las operaciones necesarias correctamente
    return {
        "status": "OK",
        "mensaje": "CSV generado y subido correctamente",
    }