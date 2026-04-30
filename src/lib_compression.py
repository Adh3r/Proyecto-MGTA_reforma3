# 1. Penalty: Only for flights past the delay cutoff.
# 2. Compression: Needs to happen once we cleared out the cancelled flights.
# 3. Slot ownership: Remember these are airline-owned, so they don't lose the reference.
# 4. Sorting: Stay with FIFO for the time.
import pandas as pd
import numpy as np
from config import FS_CANDIDATE

def penalty_and_compression(df_vuelos_asignados: pd.DataFrame, num_penalizados: int = 12) -> pd.DataFrame:
    """
    Aplica un corte a los vuelos con más retraso y comprime el resto
    respetando la aerolinea de los slots y aplicando compresión global si la aerolínea no puede usar el hueco.

    inputs :
        df_vuelos_asignados: DataFrame resultante de asignar_slots_rbs() o calcular_delays()
        num_penalizados: Número de vuelos a los que se les quitará el slot.

    Returns:
        DataFrame con los slots reasignados tras la compresión.
    """
    df = df_vuelos_asignados.copy()

    # Only penalize the flights we can regulate (FS_CANDIDATE). 
    # EXEMPTS cannot be touched.

    candidatos = df[df['flight_status'] == FS_CANDIDATE]
    
    if candidatos.empty:
        return df # Nothing to compress
        
    peores_vuelos = candidatos.nlargest(num_penalizados, 'total_delay')
    #nlargest --> returns the n rows hith higher values in the selected column

    # identify the most affected airline
    counts_afectados = peores_vuelos['airline'].value_counts()
    top_airline = counts_afectados.index[0] if not counts_afectados.empty else "N/A"
    top_count = counts_afectados.max() if not counts_afectados.empty else 0

    #free the slots but save the airline-ownership
    slots_liberados = peores_vuelos[['assigned_slot', 'airline']].dropna()
    slots_abiertos = [ {'time': row['assigned_slot'], 'airline': row['airline']} for _, row in slots_liberados.iterrows()]

    #erase all other atributes
    df.loc[peores_vuelos.index, 'assigned_slot'] = np.nan
    df.loc[peores_vuelos.index, 'total_delay'] = np.nan
    df.loc[peores_vuelos.index, 'air_delay'] = np.nan
    df.loc[peores_vuelos.index, 'ground_delay'] = np.nan
    
    # sort the slot list 
    slots_abiertos = sorted(slots_abiertos, key=lambda x: x['time'])

    v_movidos = 0
    ahorro_min = 0

    # COMPRESSION ALGORITHM
    while slots_abiertos:
        # first free slot
        slot_actual = slots_abiertos.pop(0)
        t_slot = slot_actual['time']
        aerolinea_dueña = slot_actual['airline']

        # Finding flights that can jump into this slot:
        # 1. Already have a later slot (assigned_slot > t_slot)
        # 2. ETA allows them to make it on time (ETA <= t_slot)
        # 3. Must be FS_CANDIDATE (don't touch exempt flights)
        elegibles = df[
            (df['assigned_slot'] > t_slot) & 
            (df['minutes_eta'] <= t_slot) & 
            (df['assigned_slot'].notna()) &
            (df['flight_status'] == FS_CANDIDATE)
        ]

        if elegibles.empty:
            continue # No one can take advantage of this slot, we lose it.

        # COMPRESSION 1: Priority for the airline that owns the slot
        elegibles_dueña = elegibles[elegibles['airline'] == aerolinea_dueña]
        
        vuelo_seleccionado_idx = None
        
        if not elegibles_dueña.empty:
            #the owner airline moves the flight to an early slot
            vuelo_seleccionado_idx = elegibles_dueña.sort_values('assigned_slot').index[0]
        else:
            # COMPRESSION 2: if the owner can't fill the slot, it frees the ownership
            # we give the slot to the next flight with the earliest ETA
            vuelo_seleccionado_idx = elegibles.sort_values('minutes_eta').index[0]

        # EXECUTE CHANGES 

        slot_dejado_libre = df.at[vuelo_seleccionado_idx, 'assigned_slot']
        aerolinea_que_deja_slot = df.at[vuelo_seleccionado_idx, 'airline']

        # Saving time
        v_movidos += 1
        ahorro_min += (slot_dejado_libre - t_slot)

        #move the flight to the new slot
        df.at[vuelo_seleccionado_idx, 'assigned_slot'] = t_slot

        # the slot that this moved flight has left free goes to the common bag of open slots but mantains the airline-ownership
        slots_abiertos.append({'time': slot_dejado_libre, 'airline': aerolinea_que_deja_slot})
        
        # Resort the list to ensure we always give priority to the earliest
        slots_abiertos = sorted(slots_abiertos, key=lambda x: x['time'])

    # Results printed in core
    print(f"\n--- REPORTE DE COMPRESIÓN ---")
    print(f"Aerolínea más afectada (penalizaciones): {top_airline} con {top_count} vuelos")
    print(f"Vuelos modificados por compresión: {v_movidos}")
    print(f"Delay total ahorrado: {ahorro_min:.2f} minutos")
    print(f"-----------------------------\n")

    return df
