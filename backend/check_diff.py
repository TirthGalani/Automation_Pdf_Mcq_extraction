import json
import re

def get_job_info(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        text = f.read()
    pattern = re.compile(r'"([0-9a-fA-F\-]{36})":\s*\{')
    keys = pattern.findall(text)
    print(f"File {filename}: {len(keys)} job keys found.")
    for k in keys:
        pos = text.find(f'"{k}":')
        chunk = text[pos:pos+500]
        # find file_name or progress_message
        fname_m = re.search(r'"file_name":\s*"([^"]+)"', chunk)
        fname = fname_m.group(1) if fname_m else "unknown"
        q_m = re.search(r'"total_questions":\s*(\d+)', chunk)
        q = q_m.group(1) if q_m else "?"
        status_m = re.search(r'"status":\s*"([^"]+)"', chunk)
        status = status_m.group(1) if status_m else "?"
        print(f"  [{k}] status={status} file={fname} total_q={q}")

print("--- CURRENT .jobs_cache.json ---")
get_job_info(".jobs_cache.json")
print("\n--- BACKUP .jobs_cache.corrupted.bak ---")
get_job_info(".jobs_cache.corrupted.bak")
