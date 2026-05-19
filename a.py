import cubiomespi as cb
import multiprocessing as mp
import sys
import random
import math
import os

# === ADJUSTABLE VARIABLES ===
TARGET_SEEDS = 30              
SEARCH_RADIUS = 3000           # Radius to search for villages and biomes
GRID_STEP = 128                # Resolution of the biome grid scan (128 is optimal for speed/accuracy)

MIN_UNIQUE_VILLAGE_BIOMES = 2  # Disregards seeds with fewer than this many unique village types
MIN_TOTAL_VILLAGES = 10         # Minimum total number of villages required in the radius

MAX_DESERT_SNOW_DISTANCE = 1500 # Maximum allowed distance between a Desert and Snowy Plains
SWAMP_PATH_TOLERANCE = 100      # How far off the direct path the Swamp is allowed to be (in blocks)

# Target unique village biomes
VILLAGE_BIOMES = {
    "Plains": {1, 177}, 
    "Desert": {2},      
    "Taiga": {5},       
    "Snowy": {12},      
    "Savanna": {35}     
}

# 1 Block of scan step represents this much physical block area
AREA_PER_POINT = GRID_STEP ** 2

def get_distance(p1, p2):
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

def check_seed(seed):
    g = cb.Generator(cb.MCVersion.MC_1_20, seed, cb.Dimension.DIM_OVERWORLD)
    
    found_types = set()
    total_villages = 0
    region_range = (SEARCH_RADIUS // 512) + 1
    
    # === 1. VILLAGES ===
    for rx in range(-region_range, region_range + 1):
        for rz in range(-region_range, region_range + 1):
            pos = cb.get_structure_pos(cb.Structure.Village, g, rx, rz)
            if pos:
                x, z = pos
                if abs(x) <= SEARCH_RADIUS and abs(z) <= SEARCH_RADIUS:
                    if cb.is_viable_structure_pos(cb.Structure.Village, g, x, z):
                        total_villages += 1
                        biome_id = int(cb.get_biome_at(g, x, 64, z))
                        for v_type, valid_ids in VILLAGE_BIOMES.items():
                            if biome_id in valid_ids:
                                found_types.add(v_type)
                                break
                                
    # STRICT FILTERS for Villages
    if len(found_types) < MIN_UNIQUE_VILLAGE_BIOMES or total_villages < MIN_TOTAL_VILLAGES:
        return None

    # === 2. BIOME SIZE MEASUREMENT & GRID MAPPING ===
    desert_points = []
    snowy_points = []
    swamp_points = []
    
    # Counters for area calculation
    counts = {
        "savanna": 0, "plains": 0, "taiga": 0, 
        "mushroom": 0, "old_growth": 0, "stony_peaks": 0, "pale_garden": 0
    }
    
    for x in range(-SEARCH_RADIUS, SEARCH_RADIUS, GRID_STEP):
        for z in range(-SEARCH_RADIUS, SEARCH_RADIUS, GRID_STEP):
            b_id = int(cb.get_biome_at(g, x, 64, z))
            
            # Map Pathfinding biomes
            if b_id == 2: desert_points.append((x, z))
            elif b_id == 12: snowy_points.append((x, z))
            elif b_id in {6, 71}: swamp_points.append((x, z)) # Swamp & Mangrove
            
            # Count General & Bonus biomes
            elif b_id in {35, 36}: counts["savanna"] += 1
            elif b_id in {1, 177}: counts["plains"] += 1
            elif b_id in {5, 133}: counts["taiga"] += 1
            elif b_id in {14, 15}: counts["mushroom"] += 1
            elif b_id in {32, 33}: counts["old_growth"] += 1
            elif b_id == 76: counts["stony_peaks"] += 1
            elif b_id == 999: counts["pale_garden"] += 1 # Update with future Pale Garden ID

    # If missing required biomes entirely, throw out seed
    if not desert_points or not snowy_points or not swamp_points:
        return None
        
    # === 3. "SWAMP IN BETWEEN" PATHFINDING LOGIC ===
    ds_pairs = []
    for d in desert_points:
        for s in snowy_points:
            ds_pairs.append((get_distance(d, s), d, s))
            
    # Sort pairs to find the absolute shortest desert-to-snow path first
    ds_pairs.sort(key=lambda x: x[0])
    
    min_valid_dist = float('inf')
    
    for ds_dist, d, s in ds_pairs:
        if ds_dist > MAX_DESERT_SNOW_DISTANCE:
            break # Exceeded our maximum allowed distance, skip remaining
            
        if ds_dist > min_valid_dist:
            break # We already found a closer valid pair
            
        # Check if any swamp point lies on the path between this Desert and Snow point
        for w in swamp_points:
            # Triangle Inequality: Dist(D,W) + Dist(W,S) should be roughly equal to Dist(D,S)
            if get_distance(d, w) + get_distance(w, s) <= ds_dist + SWAMP_PATH_TOLERANCE:
                min_valid_dist = ds_dist
                break # Valid path found!

    # STRICT FILTER: Disregard if no swamp is between a close desert and snow
    if min_valid_dist == float('inf'):
        return None

    # === 4. WOODLAND MANSION (Bonus Structure) ===
    has_mansion = False
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

    # === 5. COMPILE SIZES & BONUSES ===
    sizes = {
        "desert": len(desert_points) * AREA_PER_POINT,
        "snow": len(snowy_points) * AREA_PER_POINT,
        "swamp": len(swamp_points) * AREA_PER_POINT,
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

    return (seed, total_villages, len(found_types), min_valid_dist, plus_points, sizes, has_mansion)

def main():
    cores = mp.cpu_count()
    print(f"Igniting {cores} CPU cores for parallel processing...")
    
    BATCH_SIZE = 1000
    batches_processed = 0
    found_seeds = []
    
    with mp.Pool(processes=cores) as pool:
        while len(found_seeds) < TARGET_SEEDS:
            batches_processed += 1
            total_checked = batches_processed * BATCH_SIZE
            
            sys.stdout.write(f"Processing batch {batches_processed*1000} | Good Seeds: {len(found_seeds)}/{TARGET_SEEDS}...\r")
            sys.stdout.flush()
            
            seeds_to_check = [random.randint(-2**63, 2**63 - 1) for _ in range(BATCH_SIZE)]
            
            for result in pool.imap_unordered(check_seed, seeds_to_check, chunksize=50):
                if result:
                    seed, total_villages, unique_count, min_dist, plus_points, sizes, has_mansion = result
                    
                    if not any(s[0] == seed for s in found_seeds):
                        found_seeds.append(result)
                        print(f"\n[+] Match! Seed: {seed:<20} | Dist: {int(min_dist):<4} | Vil: {total_villages:<2} | Bonus: {plus_points}")
                        
                    if len(found_seeds) >= TARGET_SEEDS:
                        pool.terminate()
                        break
                        
            if len(found_seeds) >= TARGET_SEEDS:
                break

    # === RANKING SYSTEM ===
    # Priority: 1. Distance (Asc) | 2. Villages (Desc) | 3. Bonuses (Desc) | 4. Unique Types (Desc)
    ranked_seeds = sorted(found_seeds, key=lambda x: (x[3], -x[1], -x[4], -x[2]))

    print("\n\n" + "="*80)
    print(f"🏆 TOP {TARGET_SEEDS} SEEDS SAVED TO SQL 🏆")
    print("="*80)
    
    sql_filename = "top_50_seeds.sql"
    with open(sql_filename, "w", encoding="utf-8") as f:
        # Prepare SQL table with size columns
        f.write("CREATE TABLE IF NOT EXISTS best_seeds (\n")
        f.write("    rank INT,\n")
        f.write("    seed BIGINT,\n")
        f.write("    desert_to_snow_dist INT,\n")
        f.write("    villages INT,\n")
        f.write("    unique_villages INT,\n")
        f.write("    bonus_points INT,\n")
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

        for i, (seed, total_villages, unique_count, min_dist, plus_points, sz, has_mansion) in enumerate(ranked_seeds, 1):
            url = f"https://chunkbase.com/apps/seed-map#seed={seed}"
            
            # Short console output
            print(f"#{i:02d} | Dist: {int(min_dist):<4} | Vil: {total_villages:<2} | {url}")
            
            # SQL Insert with explicit sizes
            f.write(f"INSERT INTO best_seeds VALUES ({i}, {seed}, {int(min_dist)}, {total_villages}, {unique_count}, {plus_points}, {has_mansion}, ")
            f.write(f"{sz['desert']}, {sz['snow']}, {sz['swamp']}, {sz['savanna']}, {sz['plains']}, {sz['taiga']}, ")
            f.write(f"{sz['mushroom']}, {sz['old_growth']}, {sz['stony_peaks']}, {sz['pale_garden']}, '{url}');\n")

    print("="*80)
    print(f"✅ Data (including biome sizes) successfully saved to {os.path.abspath(sql_filename)}")

if __name__ == "__main__":
    main()