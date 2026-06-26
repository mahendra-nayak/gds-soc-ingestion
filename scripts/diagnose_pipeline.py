from pathlib import Path
from scripts.ingest_lib import ClientConfig, build_manifest, scrub_credentials, dispatch_by_geo, _connector_cfg
import zipfile

zip_path = Path('tests/fixtures/soc_sample.zip')
workdir = Path('run_output')

with zipfile.ZipFile(zip_path) as zf:
    zf.extractall(workdir)

root = workdir
_pipeline_dirs = {'output', 'quarantine'}
subdirs = [p for p in root.iterdir() if p.is_dir() and p.name not in _pipeline_dirs]
if len(subdirs) == 1:
    root = subdirs[0]
    print('Descended into', root)

cfg = ClientConfig.load('assets/client_config.SOC_USA.yaml')
manifest = build_manifest(root, cfg)
geo_files = dispatch_by_geo(manifest)
usa_files = geo_files['USA']
print(f'USA files: {len(usa_files)}')

can_files = geo_files['CAN']
print(f'CAN files: {len(can_files)}')

can_cfg = ClientConfig.load('assets/client_config.SOC_CAN.yaml')

scrubbed_usa = scrub_credentials(usa_files, cfg)
scrubbed_can = scrub_credentials(can_files, can_cfg)

import gzip as _gzip

def http_strip_body(raw: bytes) -> bytes:
    sep = b'\r\n\r\n'
    return raw.split(sep, 1)[1] if sep in raw else raw

def maybe_gunzip(b: bytes) -> bytes:
    return _gzip.decompress(b) if b[:2] == b'\x1f\x8b' else b

def check_json_files(files, geo_cfg, label, strategies):
    for sf in files:
        conn = _connector_cfg(sf.connector, geo_cfg)
        if conn and conn.get('is_credential'):
            continue
        strat = (conn or {}).get('parse_strategy', 'raw_json')
        if strat not in strategies:
            continue
        try:
            if strat == 'gds_envelope_json':
                text = sf.path.read_text(encoding='utf-8').strip()
            else:  # raw_json
                raw = sf.path.read_bytes()
                text = maybe_gunzip(http_strip_body(raw)).decode('utf-8', errors='replace').strip()
            if not text:
                print(f'[{label}] EMPTY ({strat}): {sf.path.name}  connector={sf.connector}')
            elif not text.startswith(('{', '[')):
                print(f'[{label}] NOT-JSON ({strat}): {sf.path.name}  connector={sf.connector}  starts={repr(text[:40])}')
        except Exception as e:
            print(f'[{label}] ERROR ({strat}): {sf.path.name}  connector={sf.connector}  err={e}')

check_json_files(usa_files, cfg, 'USA', {'gds_envelope_json', 'raw_json'})
check_json_files(can_files, can_cfg, 'CAN', {'gds_envelope_json', 'raw_json'})
