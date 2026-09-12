"""Use the packaged DLLs for every Windows test executable."""
from pathlib import Path
import shutil

runtime = list(Path('native-output').glob('*.dll'))
if not any(p.name.lower().startswith('libass-') for p in runtime):
    raise RuntimeError('The custom libass runtime is missing')
directories = {Path('build-mpv')}
directories.update(p.parent for p in Path('build-mpv/test').rglob('*.exe'))
for directory in directories:
    for source in runtime:
        shutil.copy2(source, directory / source.name)
print(f'Installed the bundle runtime beside tests in {len(directories)} directories.')
