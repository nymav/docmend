"""Explicit live compatibility probe using public synthetic evidence only.

Requires --allow-provider-request; may incur charges. Never prints credentials.
"""
import argparse,json
from pathlib import Path
from docmend.config import Config
from docmend.models import DocMendError
from docmend.provider import ModelProvider

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--allow-provider-request',action='store_true');p.add_argument('--embedding',action='store_true');args=p.parse_args()
    if not args.allow_provider_request:raise DocMendError('Explicit --allow-provider-request is required; the probe can incur charges')
    cfg=Config.from_text(args.config.read_text());provider=ModelProvider(cfg)
    result=provider.json('Return {"probe":"ok"}.',{'synthetic_probe':'Return a JSON probe response; no repository data is sent.'})
    if result.get('probe')!='ok':raise DocMendError('Provider JSON compatibility probe failed')
    dimensions=None
    if args.embedding:
        vectors=provider.embed(['DocMend public compatibility probe'])
        dimensions=len(vectors[0])
    print(json.dumps({'chat_json':'passed','embedding_dimensions':dimensions,'requests':provider.request_count,'elapsed_ms':provider.budget.elapsed_ms(),'evidence':'live synthetic compatibility probe; not model quality evaluation'}))
    return 0
if __name__=='__main__':raise SystemExit(main())
