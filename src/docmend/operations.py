"""Bounded read-only GitHub App installation-token validation."""
import json
import re
from urllib.request import Request, build_opener
from urllib.error import HTTPError, URLError
from .provider import NoRedirect
from .models import DocMendError


def validate_installation(repository: str, token: str, *, opener=None) -> dict:
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository) or not token:
        raise DocMendError('Repository and installation token are required')
    opener=opener or build_opener(NoRedirect())
    for page in range(1,11):
        request=Request(f'https://api.github.com/installation/repositories?per_page=100&page={page}',headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','User-Agent':'docmend'})
        try:
            with opener.open(request,timeout=30) as response:
                raw=response.read(5_000_001)
                if len(raw)>5_000_000:raise ValueError()
                result=json.loads(raw)
                repos=result['repositories']
                if not isinstance(repos,list):raise ValueError()
                if any(r.get('full_name','').casefold()==repository.casefold() for r in repos):
                    return {'repository':repository,'installation_repository_access':True,'write_permissions':'not exercised','mutations':0}
                if len(repos)<100:break
        except (HTTPError,URLError,OSError,ValueError,KeyError,TypeError) as exc:
            raise DocMendError('GitHub App validation failed; use a valid installation token. Credentials and response bodies are not logged.') from exc
    raise DocMendError('Repository not available to this installation token within the bounded scan')
