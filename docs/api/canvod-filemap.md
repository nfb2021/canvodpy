# canvod.filemap API Reference

Filename convention, mapping, validation, and cataloging.

## Convention

::: canvod.filemap.convention
    options:
      members:
        - CanVODFilename
        - ReceiverType
        - FileType

## Mapping

::: canvod.filemap.mapping
    options:
      members:
        - VirtualFile
        - FilenameMapper

## Recipe

::: canvod.filemap.recipe
    options:
      members:
        - NamingRecipe

## Patterns

::: canvod.filemap.patterns
    options:
      members:
        - SourcePattern
        - BUILTIN_PATTERNS

## Validation

::: canvod.filemap.validator
    options:
      members:
        - DataDirectoryValidator
        - ValidationReport

## Catalog

::: canvod.filemap.catalog
    options:
      members:
        - FilenameCatalog

## Configuration

::: canvod.filemap.config_models
    options:
      members:
        - SiteNamingConfig
        - ReceiverNamingConfig
        - DirectoryLayout
