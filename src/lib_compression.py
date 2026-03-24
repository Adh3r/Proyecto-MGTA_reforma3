#aplicar el penalty a los vuelos que pasen de cierto valor de delay
#hacer el algoritmo de compresion una vez que hayamos cancelado los vuelos
#recordar que los slots siguen perteneciendo a las aerolineas
#de momento seguiremos con la logica fifo
import pandas as pd
import numpy as np
from config import FS_CANDIDATE

def penalty_and_compression(df_vuelos_asignados: pd.DataFrame, num_penalizados: int = 12) -> pd.DataFrame:
    """
    Aplica un corte a los vuelos con más retraso y comprime el resto de la 
    programación respetando la aerolinea de los slots y aplicando compresión global si la aerolínea no puede usar el hueco.

    Args:
        df_vuelos_asignados: DataFrame resultante de asignar_slots_rbs() o calcular_delays()
        num_penalizados: Número de vuelos a los que se les quitará el slot.

    Returns:
        DataFrame con los slots reasignados tras la compresión.
    """
    df = df_vuelos_asignados.copy()

    # Solo penalizamos vuelos que podemos regular (FS_CANDIDATE). 
    # Los exentos no se tocan porque ya están en el aire

    candidatos = df[df['flight_status'] == FS_CANDIDATE]
    
    if candidatos.empty:
        return df # No hay nada que comprimir
        
    peores_vuelos = candidatos.nlargest(num_penalizados, 'total_delay')
    #nlargest --> devuelve las n filas con valores mas grandes en la columna seleccionada 

    #vamos a liberar los slots y guardar a que aerolineas pertenecen
    slots_liberados = peores_vuelos[['assigned_slot', 'airline']].dropna()
    slots_abiertos = [ {'time': row['assigned_slot'], 'airline': row['airline']} for _, row in slots_liberados.iterrows()]

    #vamos a borrar los atributos que no son la aerolinea de la fila que queremos dejar vacia
    df.loc[peores_vuelos.index, 'assigned_slot'] = np.nan
    df.loc[peores_vuelos.index, 'total_delay'] = np.nan
    df.loc[peores_vuelos.index, 'air_delay'] = np.nan
    df.loc[peores_vuelos.index, 'ground_delay'] = np.nan
    
    # Ordenamos la lista de huecos 
    slots_abiertos = sorted(slots_abiertos, key=lambda x: x['time'])

    # 3. ALGORITMO DE COMPRESIÓN 
    while slots_abiertos:
        # Cogemos el hueco más temprano que esté libre
        slot_actual = slots_abiertos.pop(0)
        t_slot = slot_actual['time']
        aerolinea_dueña = slot_actual['airline']

        # Buscamos qué vuelos podrian ocupar este slot:
        # - Tienen un slot asignado más tarde que este hueco (assigned_slot > t_slot)
        # - Su hora prevista de llegada (ETA) les permite llegar a este hueco (ETA <= t_slot)
        # - Son vuelos regulables (FS_CANDIDATE), no movemos exentos
        elegibles = df[
            (df['assigned_slot'] > t_slot) & 
            (df['minutes_eta'] <= t_slot) & 
            (df['assigned_slot'].notna()) &
            (df['flight_status'] == FS_CANDIDATE)
        ]

        if elegibles.empty:
            continue # Nadie puede aprovechar este hueco, se pierde.

        # COMPRESIÓN 1: Prioridad para la aerolínea dueña del slot
        elegibles_dueña = elegibles[elegibles['airline'] == aerolinea_dueña]
        
        vuelo_seleccionado_idx = None
        
        if not elegibles_dueña.empty:
            # La aerolínea dueña adelanta al vuelo que tenga el slot original más temprano
            vuelo_seleccionado_idx = elegibles_dueña.sort_values('assigned_slot').index[0]
        else:
            # COMPRESIÓN 2:Si la dueña no puede, pasa a la bolsa común
            # Se lo damos al vuelo elegible que llevaba más tiempo esperando (menor ETA)
            vuelo_seleccionado_idx = elegibles.sort_values('minutes_eta').index[0]

        # 4. EJECUTAR EL CAMBIO 

        slot_dejado_libre = df.at[vuelo_seleccionado_idx, 'assigned_slot']
        aerolinea_que_deja_slot = df.at[vuelo_seleccionado_idx, 'airline']

        # Movemos el vuelo que toca al nuevo hueco
        df.at[vuelo_seleccionado_idx, 'assigned_slot'] = t_slot

        # El hueco que este vuelo acaba de dejar atrás entra en la bolsa de slots
        # abiertos, y pertenece a la aerolínea que lo acaba de dejar.
        slots_abiertos.append({'time': slot_dejado_libre, 'airline': aerolinea_que_deja_slot})
        
        # Reordenamos la lista de huecos para asegurar que siempre atacamos el más temprano
        slots_abiertos = sorted(slots_abiertos, key=lambda x: x['time'])

    return df

    