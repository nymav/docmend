"""Read-only live installation check; no token on the command line."""
import argparse,json,os
from docmend.operations import validate_installation
p=argparse.ArgumentParser();p.add_argument('--repository',required=True);args=p.parse_args()
print(json.dumps(validate_installation(args.repository,os.environ.get('DOCMEND_APP_TOKEN',''))))
