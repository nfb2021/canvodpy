# canvod-preflight

The canVOD filename convention: `CanVODFilename` parses and builds canonical
names, and `find_overlaps` finds files whose named time spans overlap.

The mapping and validation API (`FilenameMapper`, `DataDirectoryValidator`,
the naming config models, the pattern registry and the `canvod-preflight`
command) is deprecated and will be removed with the next major version. Use
naming recipes (canvod-filemap) and `canvodpy config validate` instead.
