import cubiomespi as cb
import multiprocessing as mp
import sys
import random
import math
import os

# === ADJUSTABLE VARIABLES ===
TARGET_SEEDS = 30              
SEARCH_RADIUS = 3000           
GRID_STEP = 128                # Deep scan resolution (Used only for winning seeds)
FAST_STEP = 256                # Fast scan resolution (Used to quickly eliminate bad seeds)

MIN_UNIQUE_VILLAGE_BIOMES = 1  
MIN_TOTAL_VILLAGES = 2         

MAX_DESERT_SNOW_DISTANCE = 1250 
SPAWN_PATH_TOLERANCE = 2000      

VILLAGE_BIOMES = {
    "Plains": {1, 177}, 
    "Desert": {2},      
    "Taiga": {5},       
    "Snowy": {12},      
    "Savanna": {35}     
}

AREA_PER_POINT = GRID_STEP ** 2

def get_distance(p1, p2):
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

def check_seed(seed):
    # Provides a live feed of what the cores are doing. 
    # (Uses \r to overwrite lines so it doesn't create thousands of lines of text spam)
    if seed % 13 == 0: # Throttles the terminal print slightly so it doesn't cause I/O lag
        sys.stdout.write(f"\033[K[{mp.current_process().name}] Processing seed: {seed}\r")
        sys.stdout.flush()

    g = cb.Generator(cb.MCVersion.MC_1_20, seed, cb.Dimension.DIM_OVERWORLD)
    
    # ==========================================
    # PHASE 1: FAST ELIMINATION (Distance Check)
    # ==========================================
    desert_points_fast = []
    snowy_points_fast = []
    
    # We use FAST_STEP (256 blocks) to rapidly check if these biomes even exist
    for x in range(-SEARCH_RADIUS, SEARCH_RADIUS, FAST_STEP):
        for z in range(-SEARCH_RADIUS, SEARCH_RADIUS, FAST_STEP):
            b_id = int(cb.get_biome_at(g, x, 64, z))
            if b_id == 2: desert_points_fast.append((x, z))
            elif b_id == 12: snowy_points_fast.append((x, z))

    if not desert_points_fast or not snowy_points_fast:
        return None
        
    min_dist = float('inf')
    best_d = None
    best_s = None
    
    for d in desert_points_fast:
        for s in snowy_points_fast:
            dist = get_distance(d, s)
            if dist < min_dist:
                min_dist = dist
                best_d = d
                best_s = s

    if min_dist > MAX_DESERT_SNOW_DISTANCE or min_dist == float('inf'):
        return None

    # ==========================================
    # PHASE 2: TARGETED VILLAGE SEARCH
    # ==========================================
    spawn_in_between = False
    if get_distance(best_d, (0,0)) + get_distance((0,0), best_s) <= min_dist + SPAWN_PATH_TOLERANCE:
        spawn_in_between = True

    found_types = set()
    total_villages = 0
    
    midpoint = ((best_d[0] + best_s[0]) / 2, (best_d[1] + best_s[1]) / 2)
    village_search_radius = (min_dist / 2) + 100 
    
    # Calculate only the specific regions that overlap our Desert-to-Snow path
    min_rx = int((midpoint[0] - village_search_radius) // 512) - 1
    max_rx = int((midpoint[0] + village_search_radius) // 512) + 1
    min_rz = int((midpoint[1] - village_search_radius) // 512) - 1
    max_rz = int((midpoint[1] + village_search_radius) // 512) + 1
    
    for rx in range(min_rx, max_rx + 1):
        for rz in range(min_rz, max_rz + 1):
            pos = cb.get_structure_pos(cb.Structure.Village, g, rx, rz)
            if pos:
                x, z = pos
                if get_distance((x, z), midpoint) <= village_search_radius:
                    if cb.is_viable_structure_pos(cb.Structure.Village, g, x, z):
                        total_villages += 1
                        biome_id = int(cb.get_biome_at(g, x, 64, z))
                        for v_type, valid_ids in VILLAGE_BIOMES.items():
                            if biome_id in valid_ids:
                                found_types.add(v_type)
                                break
                                
    if len(found_types) < MIN_UNIQUE_VILLAGE_BIOMES or total_villages < MIN_TOTAL_VILLAGES:
        return None

    # ==========================================
    # PHASE 3: DEEP SCAN (Only runs on winners)
    # ==========================================
    # At this point, the seed is virtually guaranteed to be a winner. 
    # NOW we spend the CPU time to accurately measure the biomes.
    counts = {
        "savanna": 0, "plains": 0, "taiga": 0, 
        "mushroom": 0, "old_growth": 0, "stony_peaks": 0, "pale_garden": 0
    }
    
    exact_desert_pts = 0
    exact_snow_pts = 0
    swamp_points = 0
    
    for x in range(-SEARCH_RADIUS, SEARCH_RADIUS, GRID_STEP):
        for z in range(-SEARCH_RADIUS, SEARCH_RADIUS, GRID_STEP):
            b_id = int(cb.get_biome_at(g, x, 64, z))
            
            if b_id == 2: exact_desert_pts += 1
            elif b_id == 12: exact_snow_pts += 1
            elif b_id in {6, 71}: swamp_points += 1
            elif b_id in {35, 36}: counts["savanna"] += 1
            elif b_id in {1, 177}: counts["plains"] += 1
            elif b_id in {5, 133}: counts["taiga"] += 1
            elif b_id in {14, 15}: counts["mushroom"] += 1
            elif b_id in {32, 33}: counts["old_growth"] += 1
            elif b_id == 76: counts["stony_peaks"] += 1
            elif b_id == 999: counts["pale_garden"] += 1

    # Mansion Search (Full map)
    has_mansion = False
    region_range = (SEARCH_RADIUS // 512) + 1
    for rx in range(-region_range, region_range + 1):
        for rz in range(-region_range, region_range + 1):
            pos = cb.get_structure_pos(cb.Structure.Mansion, g, rx, rz)
            if pos:
                x, z = pos
                if abs(x) <= SEARCH_RADIUS and abs(z) <= SEARCH_RADIUS:
                    if cb.is_viable_structure_pos(cb.Structure.Mansion, g, x, z):
                        has_mansion = True
                        break
        if has_mansion: break

    # Compile Final Data
    sizes = {
        "desert": exact_desert_pts * AREA_PER_POINT,
        "snow": exact_snow_pts * AREA_PER_POINT,
        "swamp": swamp_points * AREA_PER_POINT,
        "savanna": counts["savanna"] * AREA_PER_POINT,
        "plains": counts["plains"] * AREA_PER_POINT,
        "taiga": counts["taiga"] * AREA_PER_POINT,
        "mushroom": counts["mushroom"] * AREA_PER_POINT,
        "old_growth": counts["old_growth"] * AREA_PER_POINT,
        "stony_peaks": counts["stony_peaks"] * AREA_PER_POINT,
        "pale_garden": counts["pale_garden"] * AREA_PER_POINT
    }
    
    plus_points = sum([
        1 if has_mansion else 0,
        1 if counts["mushroom"] > 0 else 0,
        1 if counts["old_growth"] > 0 else 0,
        1 if counts["stony_peaks"] > 0 else 0,
        1 if counts["pale_garden"] > 0 else 0
    ])
    
    if spawn_in_between:
        plus_points += 5

    return (seed, total_villages, len(found_types), min_dist, plus_points, sizes, has_mansion, spawn_in_between)

def main():
    cores = mp.cpu_count()
    print(f"Igniting {cores} CPU cores for parallel processing...\n")
    
    BATCH_SIZE = 1000
    found_seeds = []
    
    with mp.Pool(processes=cores) as pool:
        while len(found_seeds) < TARGET_SEEDS:
            seeds_to_check = [random.randint(-2**63, 2**63 - 1) for _ in range(BATCH_SIZE)]
            
            for result in pool.imap_unordered(check_seed, seeds_to_check, chunksize=50):
                if result:
                    seed, total_villages, unique_count, min_dist, plus_points, sizes, has_mansion, spawn_in_between = result
                    
                    if not any(s[0] == seed for s in found_seeds):
                        found_seeds.append(result)
                        spawn_tag = "[Spawn Between!]" if spawn_in_between else ""
                        
                        # Use \n to preserve the success line above the live core feed
                        sys.stdout.write(f"\n[+] Match! Seed: {seed:<20} | Dist: {int(min_dist):<4} | Vil: {total_villages:<2} | Bonus: {plus_points} {spawn_tag}\n")
                        
                    if len(found_seeds) >= TARGET_SEEDS:
                        pool.terminate()
                        break
                        
            if len(found_seeds) >= TARGET_SEEDS:
                break

    # === RANKING SYSTEM ===
    ranked_seeds = sorted(found_seeds, key=lambda x: (x[3], -x[1], -x[4], -x[2]))

    print("\n\n" + "="*80)
    print(f"🏆 TOP {TARGET_SEEDS} SEEDS SAVED TO SQL 🏆")
    print("="*80)
    
    sql_filename = "top_50_seeds.sql"
    with open(sql_filename, "w", encoding="utf-8") as f:
        f.write("CREATE TABLE IF NOT EXISTS best_seeds (\n")
        f.write("    rank INT,\n")
        f.write("    seed BIGINT,\n")
        f.write("    desert_to_snow_dist INT,\n")
        f.write("    villages INT,\n")
        f.write("    unique_villages INT,\n")
        f.write("    bonus_points INT,\n")
        f.write("    spawn_in_between BOOLEAN,\n")
        f.write("    has_mansion BOOLEAN,\n")
        f.write("    desert_area INT,\n")
        f.write("    snow_area INT,\n")
        f.write("    swamp_area INT,\n")
        f.write("    savanna_area INT,\n")
        f.write("    plains_area INT,\n")
        f.write("    taiga_area INT,\n")
        f.write("    mushroom_area INT,\n")
        f.write("    old_growth_area INT,\n")
        f.write("    stony_peaks_area INT,\n")
        f.write("    pale_garden_area INT,\n")
        f.write("    chunkbase_url TEXT\n")
        f.write(");\n\n")

        for i, (seed, total_villages, unique_count, min_dist, plus_points, sz, has_mansion, spawn_in_between) in enumerate(ranked_seeds, 1):
            url = f"https://chunkbase.com/apps/seed-map#seed={seed}"
            
            print(f"#{i:02d} d: {int(min_dist):<4} | v: {total_villages:<2} | {url}")
            
            f.write(f"INSERT INTO best_seeds VALUES ({i}, {seed}, {int(min_dist)}, {total_villages}, {unique_count}, {plus_points}, {spawn_in_between}, {has_mansion}, ")
            f.write(f"{sz['desert']}, {sz['snow']}, {sz['swamp']}, {sz['savanna']}, {sz['plains']}, {sz['taiga']}, ")
            f.write(f"{sz['mushroom']}, {sz['old_growth']}, {sz['stony_peaks']}, {sz['pale_garden']}, '{url}');\n")

    print("="*80)
    print(f"✅ Data successfully saved to {os.path.abspath(sql_filename)}")

if __name__ == "__main__":
    main()