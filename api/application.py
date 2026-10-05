from flask import Flask, request, jsonify
import csv
import boto3
import io
import os

app= Flask(__name__)

# Cliente S3
s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))

BUCKET_NAME = os.environ["MONTHLY_BUCKET"]
CSV_FILE_KEY = os.environ.get("MONTHLY_KEY", "datos_procesados.csv")

def obtener_csv_desde_s3():
    """
    Descarga el CSV desde S3 y lo devuelve como un lector DictReader
    """
    try:
        response = s3.get_object(Bucket=BUCKET_NAME, Key=CSV_FILE_KEY)
        contenido = response["Body"].read().decode("utf-8")
        return csv.DictReader(io.StringIO(contenido))
    except Exception:
        return None
    
def normalizar_mes(valor_mes):
    """
    Convierte '01', '02'... en enteros 1-12

    """
    #Tanto sin el mes es 01 por ejemplo como si es 1, la parte de try devolverá el mes sin el 0, si viene sin tener 0 delante, se quedará igual
    try:
        mes = int(str(valor_mes).lstrip("0") or "0")
        return mes
    
    #Si el mes no se puede convertir a entero ni un aplicando la normalización, es porque tiene una estructura incorrecta, por tanto el mes es incorrecto, así que devuelve None
    except:
        return None


def buscar_dato(year, month, columna):

    lector = obtener_csv_desde_s3()

    if lector is None:
        return "ERROR_S3"

    for fila in lector:
        try:
            anio_csv = int(fila.get("anio"))

            #Normalizar SOLO el mes del CSV
            mes_csv = normalizar_mes(fila.get("mes"))

            #Continuaría buscando en la siguiente fila porque tiene un valor invalido de mes la actual fila(normalizar_mes si devuelve None es porque el mes no es válido)
            if mes_csv is None:
                continue

        except:
            continue

        #Para las filas correctas de año y mes, comprueba si se cumple la condición y devuelve el valor de la columna indicada
        if anio_csv == year and mes_csv == month:
            return fila.get(columna)

    return None
    

def validar_parametros():
    """
    Valida year y month y devuelve (year, month, error)
    """
    parametros_correctos = {"year", "month"}

    # Detectar parámetros incorrectos
    parametros_recibidos = set(request.args.keys())   #Creamos un conjunto con los parámetros que tienen que recibirse
    if not parametros_recibidos.issubset(parametros_correctos):
        return None, None, "Parametros invalidos. Solo se permiten 'year' y 'month'."

    year_raw = request.args.get("year")
    month_raw = request.args.get("month")
    
    #CASO EN EL QUE LOS PARÁMETROS NO SE INCLUYEN
    if year_raw is None or month_raw is None:
        return None, None, "Faltan parametros obligatorios: 'year' y 'month'."


    #Caso para ver si el valor de año es correcto
    try:
        year = int(year_raw)
    except:
        return None, None, "El parametro 'year' debe ser un numero entero."

    try:
        month = int(month_raw)
    except:
        return None, None, "El parametro 'month' debe ser un numero entero."
    
    if month < 1 or month > 12:
        return None, None, "El parametro 'month' debe ser un numero entre 1 y 12."

    return year, month, None



@app.route("/maxdiff", methods=["GET"])

def maxdiff():
    year, month, error = validar_parametros() #Comenzamos validando los parámetros de entrada

    #Si validar parámetros dentro de error devuelve None, perfecto, no hay error, de lo contrario, se ejecutará este if
    if error:
        return jsonify({"error": error}), 400

    #Si no hay errores buscamos el dato en el fichero csv del bucket de s3
    valor = buscar_dato(year, month, "diff_temperatura")


    #Si nos devuelve este error, es porque directamente no hay fichero csv en el bucket y por tanto no hay nada que leer
    if valor == "ERROR_S3":
        return jsonify({"error": "Error al leer los datos desde S3"}), 500

    #Si devuelve este error, es porque la funcion buscar_dato nos ha devuelto None, lo cual significa que ha buscado en todas las filas y no ha encontrado coincidencias
    if valor is None:
        return jsonify({"error": "No existen datos para esa fecha"}), 404

    return jsonify({
        "Año": year,
        "Mes": month,
        "Diferencia de temperaturas maximas": valor
    })

@app.route("/sd", methods=["GET"])

def sd():
    year, month, error = validar_parametros()

    if error:
        return jsonify({"error": error}), 400

    valor = buscar_dato(year, month, "desviacion_maxima")

    if valor == "ERROR_S3":
        return jsonify({"error": "Error al leer los datos desde S3"}), 500

    if valor is None:
        return jsonify({"error": "No existen datos para esa fecha"}), 404

    return jsonify({
        "Año": year,
        "Mes": month,
        "Desviacion maxima": valor
    })

@app.route("/temp", methods=["GET"])

def temp():
    year, month, error = validar_parametros()

    if error:
        return jsonify({"error": error}), 400

    valor = buscar_dato(year, month, "temperatura_media")

    if valor == "ERROR_S3":
        return jsonify({"error": "Error al leer los datos desde S3"}), 500

    if valor is None:
        return jsonify({"error": "No existen datos para esa fecha"}), 404

    return jsonify({
        "Año": year,
        "Mes": month,
        "Temperatura media": valor
    })

@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


if __name__ == "__main__":

    port = int(os.environ.get('PORT', 5000))

    app.run(debug=False, host='0.0.0.0', port=port)