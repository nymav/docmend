"""Measure executable-line coverage using stdlib tracing, not an inflated test count."""
import json,sys,trace,types,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def executable_lines(code):
    lines={line for _,_,line in code.co_lines() if line is not None and line>0}
    for value in code.co_consts:
        if isinstance(value,types.CodeType):lines.update(executable_lines(value))
    return lines

def main():
    tracer=trace.Trace(count=True,trace=False,ignoredirs=[sys.base_prefix])
    def run():
        suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
        return unittest.TextTestRunner(verbosity=1).run(suite)
    result=tracer.runfunc(run)
    counts=tracer.results().counts;modules=[]
    for path in sorted((ROOT/'src/docmend').glob('*.py')):
        source=path.read_text();lines=executable_lines(compile(source,str(path),'exec'))
        hit={line for (filename,line),count in counts.items() if Path(filename).resolve()==path.resolve() and count and line in lines}
        modules.append({'module':path.name,'executable_lines':len(lines),'covered_lines':len(hit),'coverage':len(hit)/len(lines) if lines else 1,'missing_lines':sorted(lines-hit)})
    total=sum(x['executable_lines'] for x in modules);covered=sum(x['covered_lines'] for x in modules)
    output={'instrumentation':'stdlib trace with recursively compiled code-object line tables; executable-line coverage only, not branch coverage','python':sys.version.split()[0],'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'lines':total,'covered_lines':covered,'line_coverage':covered/total,'modules':modules}
    dest=ROOT/'artifacts/evaluation/coverage';dest.mkdir(parents=True,exist_ok=True);(dest/'coverage.json').write_text(json.dumps(output,indent=2)+'\n')
    report=['# Executable-line coverage','','Measured during the unit/integration suite with stdlib tracing. This is not branch coverage.','','| Module | Covered / executable lines | Coverage |','|---|---:|---:|']
    report += [f'| {x["module"]} | {x["covered_lines"]} / {x["executable_lines"]} | {x["coverage"]:.1%} |' for x in modules]
    report += ['',f'**Overall: {covered}/{total} = {covered/total:.1%}. Tests: {result.testsRun}; failures: {len(result.failures)}; errors: {len(result.errors)}.**','']
    (dest/'REPORT.md').write_text('\n'.join(report));print(json.dumps({k:output[k] for k in ['tests_run','lines','covered_lines','line_coverage']}));return 0 if result.wasSuccessful() else 1
if __name__=='__main__':raise SystemExit(main())
