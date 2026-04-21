# Usa astropy.io.fits para abrir el archivo.
# Imprime la cabecera (header) para ver los metadatos
# (estación, frecuencias, tiempo).
# Extrae la matriz de datos a un objeto NumPy.
# Si logras imprimir las dimensiones de la matriz
# (ej. 200x3600), habrás superado el primer gran escollo técnico.

import os
import glob
import numpy as np
from astropy.io import fits

# 1. Ruta a la carpeta de datos
carpeta_datos = 'C:\\Users\\alfon\\Escritorio\\TFG AstroDoncel\\data'
archivos_fits = glob.glob(os.path.join(carpeta_datos, '*SIGUENZA*.fit*'))

if not archivos_fits:
    print(f"\n[ERROR] No se encontraron archivos FITS en: {carpeta_datos}")
else:
    print(f"\nSe encontraron {len(archivos_fits)} archivos FITS. Procesando...")
    for ruta_archivo in archivos_fits:
        try:
            print("\n" + "="*60)
            # 2. Abrir el archivo FITS
            print(f"Abriendo archivo: {ruta_archivo}...")
            archivo_fits = fits.open(ruta_archivo)
            
            # 3. Mostrar la estructura de los datos (HDUs)
            # print("--- Estructura del fichero FITS ---")
            # archivo_fits.info() # Descomentar para ver los HDUs de cada archivo
            
            # 4. Extraer los datos reales
            # Normalmente, en los FITS de e-Callisto, la matriz de datos principal está en el índice 0
            datos_espectrograma = archivo_fits[0].data
            cabecera = archivo_fits[0].header

            # Vamos a ver qué más hay en el archivo descomentando el info()
            print("\n--- Inspeccionando las tablas anexas ---")
            archivo_fits.info()
            
            # --- Extracción de Ejes (Tiempos y Frecuencias) ---
            print("\n--- Extrayendo Ejes ---")
            try:
                # Accedemos a la tabla anexa (índice 1)
                tabla_anexa = archivo_fits[1].data
                
                # Como es 1 fila que contiene los arrays completos, accedemos a la posición [0]
                tiempos = tabla_anexa['TIME'][0]
                frecuencias = tabla_anexa['FREQUENCY'][0]
                
                print(f"Eje X (Tiempos): Se han extraído {len(tiempos)} marcas de tiempo.")
                print(f"Eje Y (Frecuencias): Se han extraído {len(frecuencias)} frecuencias.")
                print(f"Rango de frecuencias: de {frecuencias[0]:.2f} MHz a {frecuencias[-1]:.2f} MHz")
                
            except KeyError as e:
                print(f"[AVISO] No se encontraron las columnas TIME o FREQUENCY en la tabla: {e}")
            except Exception as e:
                print(f"[ERROR] Fallo al extraer los ejes: {e}")

            # 5. Comprobaciones de éxito
            print("\n--- ¡Éxito! ---")
            if datos_espectrograma is not None:
                print(f"Dimensiones de la matriz de datos: {datos_espectrograma.shape}")
            else:
                print("El índice 0 no contiene matriz de datos de imagen.")
            print(f"Estación de observación: {cabecera.get('INSTRUME', 'Desconocida')}")
            print(f"Fecha de observación: {cabecera.get('DATE-OBS', 'Desconocida')}")

            # --- Sustracción de fondo (mediana por fila/frecuencia) ---
            fondo = np.median(datos_espectrograma, axis=1, keepdims=True)
            datos_limpios = datos_espectrograma.astype(np.float32) - fondo

            # --- Exportar datos a JSON para el frontend ---
            import json

            ruta_json = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                '..', 'frontend', 'public', 'datos_prueba.json'
            )
            ruta_json = os.path.normpath(ruta_json)

            payload = {
                'tiempos': [round(float(v), 3) for v in tiempos],
                'frecuencias': [round(float(v), 3) for v in frecuencias],
                'datos': [[round(float(v), 2) for v in fila] for fila in datos_limpios],
            }
            with open(ruta_json, 'w', encoding='utf-8') as f:
                json.dump(payload, f)
            print(f"\n[JSON] Datos exportados a: {ruta_json}")

            # Cerrar el archivo por seguridad
            archivo_fits.close()

            break # Rompemos el bucle para analizar solo el primer archivo por ahora

        except Exception as e:
            print(f"\n[ERROR] Ha ocurrido un fallo analizando {os.path.basename(ruta_archivo)}: {e}")
