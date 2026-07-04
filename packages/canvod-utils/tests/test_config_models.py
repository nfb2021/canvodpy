"""Unit tests for canvod.utils.config.models Pydantic validators.

Tests the validation logic, cross-field constraints, and helper methods
on the configuration models. No YAML files or filesystem config required.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from canvod.utils.config.models import (
    AuxDataConfig,
    CanvodConfig,
    ChunkStrategy,
    CompressionConfig,
    CredentialsConfig,
    IcechunkConfig,
    MetadataConfig,
    ProcessingConfig,
    ProcessingParams,
    ReceiverConfig,
    SidsConfig,
    SiteConfig,
    SitesConfig,
    StorageConfig,
)

# ===================================================================
# MetadataConfig
# ===================================================================


class TestMetadataConfig:
    def test_valid_metadata(self):
        m = MetadataConfig(
            author="Test User",
            email="test@example.com",
            institution="Test Uni",
        )
        assert m.author == "Test User"

    def test_invalid_email_raises(self):
        with pytest.raises(ValidationError, match="email"):
            MetadataConfig(
                author="Test",
                email="not-an-email",
                institution="Uni",
            )

    def test_to_attrs_dict_required_fields(self):
        m = MetadataConfig(
            author="Alice",
            email="alice@uni.edu",
            institution="Uni",
        )
        d = m.to_attrs_dict()
        assert d["author"] == "Alice"
        assert d["email"] == "alice@uni.edu"
        assert d["institution"] == "Uni"

    def test_to_attrs_dict_optional_fields_excluded_when_none(self):
        m = MetadataConfig(
            author="A",
            email="a@b.com",
            institution="U",
        )
        d = m.to_attrs_dict()
        assert "department" not in d
        assert "research_group" not in d
        assert "website" not in d

    def test_to_attrs_dict_optional_fields_included_when_set(self):
        m = MetadataConfig(
            author="A",
            email="a@b.com",
            institution="U",
            department="Dept",
            research_group="Group",
            website="https://example.com",
        )
        d = m.to_attrs_dict()
        assert d["department"] == "Dept"
        assert d["research_group"] == "Group"
        assert d["website"] == "https://example.com"


# ===================================================================
# ProcessingParams — resource_mode validator
# ===================================================================


class TestProcessingParams:
    def test_auto_mode_defaults(self):
        p = ProcessingParams()
        assert p.resource_mode == "auto"
        assert p.n_max_threads is None

    def test_manual_mode_requires_n_max_threads(self):
        with pytest.raises(ValidationError, match="n_max_threads is required"):
            ProcessingParams(resource_mode="manual")

    def test_manual_mode_with_threads(self):
        p = ProcessingParams(resource_mode="manual", n_max_threads=4)
        assert p.n_max_threads == 4

    def test_auto_mode_with_threads_warns(self):
        with pytest.warns(UserWarning, match="ignores n_max_threads"):
            ProcessingParams(resource_mode="auto", n_max_threads=4)

    def test_n_max_threads_bounds(self):
        with pytest.raises(ValidationError):
            ProcessingParams(resource_mode="manual", n_max_threads=0)  # ge=1
        with pytest.raises(ValidationError):
            ProcessingParams(resource_mode="manual", n_max_threads=101)  # le=100

    def test_batch_hours_bounds(self):
        with pytest.raises(ValidationError):
            ProcessingParams(batch_hours=0)  # gt=0
        with pytest.raises(ValidationError):
            ProcessingParams(batch_hours=721)  # le=720

    def test_nice_priority_bounds(self):
        with pytest.raises(ValidationError):
            ProcessingParams(nice_priority=-1)  # ge=0
        with pytest.raises(ValidationError):
            ProcessingParams(nice_priority=20)  # le=19

    def test_resolve_resources_auto(self):
        p = ProcessingParams(resource_mode="auto")
        r = p.resolve_resources()
        assert r["n_workers"] is None
        assert r["max_memory_gb"] is None

    def test_resolve_resources_manual(self):
        p = ProcessingParams(
            resource_mode="manual",
            n_max_threads=8,
            max_memory_gb=32.0,
            nice_priority=10,
        )
        r = p.resolve_resources()
        assert r["n_workers"] == 8
        assert r["max_memory_gb"] == 32.0
        assert r["nice_priority"] == 10

    def test_default_keep_rnx_vars(self):
        p = ProcessingParams()
        assert p.keep_rnx_vars == ["SNR", "Pseudorange", "Phase", "Doppler"]


# ===================================================================
# AuxDataConfig
# ===================================================================


class TestAuxDataConfig:
    def test_defaults(self):
        a = AuxDataConfig()
        assert a.agency == "COD"
        assert a.product_type == "final"

    def test_invalid_product_type(self):
        with pytest.raises(ValidationError, match="product_type"):
            AuxDataConfig(product_type="invalid")

    def test_ftp_servers_with_cddis(self):
        a = AuxDataConfig()
        servers = a.get_ftp_servers("user@nasa.gov")
        assert len(servers) == 2
        assert "nasa" in servers[0][0]
        assert servers[0][1] == "user@nasa.gov"
        assert "esa" in servers[1][0]
        assert servers[1][1] is None

    def test_ftp_servers_without_cddis(self):
        a = AuxDataConfig()
        servers = a.get_ftp_servers(None)
        assert len(servers) == 1
        assert "esa" in servers[0][0]


# ===================================================================
# ReceiverConfig — scs_from validation
# ===================================================================


class TestReceiverConfig:
    def test_canopy_without_scs_from(self):
        rc = ReceiverConfig(type="canopy", directory="can/raw")
        assert rc.scs_from is None

    def test_canopy_with_scs_from_raises(self):
        with pytest.raises(ValidationError, match="must not be set for canopy"):
            ReceiverConfig(type="canopy", directory="can/raw", scs_from="all")

    def test_reference_requires_scs_from(self):
        with pytest.raises(ValidationError, match="required for reference"):
            ReceiverConfig(type="reference", directory="ref/raw")

    def test_reference_with_scs_from_all(self):
        rc = ReceiverConfig(type="reference", directory="ref/raw", scs_from="all")
        assert rc.scs_from == "all"

    def test_reference_with_scs_from_list(self):
        rc = ReceiverConfig(
            type="reference",
            directory="ref/raw",
            scs_from=["canopy_01", "canopy_02"],
        )
        assert rc.scs_from == ["canopy_01", "canopy_02"]


# ===================================================================
# SiteConfig — cross-receiver validation
# ===================================================================


class TestSiteConfig:
    def _make_site(self, **overrides):
        defaults = {
            "gnss_site_data_root": "/data/site",
            "receivers": {
                "canopy_01": ReceiverConfig(type="canopy", directory="can/raw"),
                "reference_01": ReceiverConfig(
                    type="reference", directory="ref/raw", scs_from="all"
                ),
            },
        }
        defaults.update(overrides)
        return SiteConfig(**defaults)

    def test_valid_site(self):
        site = self._make_site()
        assert site.get_base_path() == Path("/data/site")

    def test_get_canopy_receiver_names(self):
        site = self._make_site()
        assert site.get_canopy_receiver_names() == ["canopy_01"]

    def test_resolve_scs_from_all(self):
        site = self._make_site()
        result = site.resolve_scs_from("reference_01")
        assert result == ["canopy_01"]

    def test_resolve_scs_from_specific_list(self):
        site = SiteConfig(
            gnss_site_data_root="/data",
            receivers={
                "c1": ReceiverConfig(type="canopy", directory="c1"),
                "c2": ReceiverConfig(type="canopy", directory="c2"),
                "r1": ReceiverConfig(type="reference", directory="r1", scs_from=["c1"]),
            },
        )
        assert site.resolve_scs_from("r1") == ["c1"]

    def test_resolve_scs_from_on_canopy_raises(self):
        site = self._make_site()
        with pytest.raises(ValueError, match="only applies to reference"):
            site.resolve_scs_from("canopy_01")

    def test_scs_from_references_nonexistent_canopy_raises(self):
        with pytest.raises(ValidationError, match="not a canopy receiver"):
            SiteConfig(
                gnss_site_data_root="/data",
                receivers={
                    "c1": ReceiverConfig(type="canopy", directory="c1"),
                    "r1": ReceiverConfig(
                        type="reference",
                        directory="r1",
                        scs_from=["nonexistent"],
                    ),
                },
            )

    def test_get_reference_canopy_pairs(self):
        site = SiteConfig(
            gnss_site_data_root="/data",
            receivers={
                "c1": ReceiverConfig(type="canopy", directory="c1"),
                "c2": ReceiverConfig(type="canopy", directory="c2"),
                "r1": ReceiverConfig(type="reference", directory="r1", scs_from="all"),
            },
        )
        pairs = site.get_reference_canopy_pairs()
        assert ("r1", "c1") in pairs
        assert ("r1", "c2") in pairs


# ===================================================================
# SidsConfig — mode validation
# ===================================================================


class TestSidsConfig:
    def test_mode_all_returns_none(self):
        s = SidsConfig(mode="all")
        assert s.get_sids() is None

    def test_mode_custom_returns_list(self):
        s = SidsConfig(mode="custom", custom_sids=["G01|L1|C", "E01|E1|C"])
        assert s.get_sids() == ["G01|L1|C", "E01|E1|C"]

    def test_mode_preset_explicit_none_raises(self):
        """Explicitly passing preset=None with mode='preset' triggers validator."""
        with pytest.raises(ValidationError, match="preset must be specified"):
            SidsConfig(mode="preset", preset=None)

    def test_mode_preset_without_name_raises(self):
        """mode='preset' with no preset name raises ValueError on get_sids()."""
        s = SidsConfig(mode="preset")
        assert s.preset is None
        with pytest.raises(ValueError, match="preset must be set"):
            s.get_sids()

    def test_mode_preset_with_name(self):
        s = SidsConfig(mode="preset", preset="gps_l1_only")
        assert s.preset == "gps_l1_only"


# ===================================================================
# StorageConfig
# ===================================================================


class TestStorageConfig:
    def test_store_paths(self, tmp_path):
        sc = StorageConfig(stores_root_dir=tmp_path)
        rinex = sc.get_rinex_store_path("rosalia")
        vod = sc.get_vod_store_path("rosalia")
        assert rinex == tmp_path / "rosalia" / "rinex"
        assert vod == tmp_path / "rosalia" / "vod"

    def test_placeholder_path_not_validated(self):
        """Placeholder paths starting with /path/ skip existence check."""
        sc = StorageConfig(stores_root_dir=Path("/path/to/stores"))
        assert sc.stores_root_dir == Path("/path/to/stores")

    def test_aux_data_dir_default_tempdir(self, tmp_path):
        sc = StorageConfig(stores_root_dir=tmp_path, aux_data_dir=None)
        aux = sc.get_aux_data_dir()
        assert aux.exists()

    def test_aux_data_dir_explicit(self, tmp_path):
        aux_dir = tmp_path / "aux"
        sc = StorageConfig(stores_root_dir=tmp_path, aux_data_dir=aux_dir)
        result = sc.get_aux_data_dir()
        assert result == aux_dir
        assert result.exists()  # should have been created


# ===================================================================
# IcechunkConfig
# ===================================================================


class TestIcechunkConfig:
    def test_defaults(self):
        ic = IcechunkConfig()
        assert ic.compression_level == 5
        assert ic.compression_algorithm == "zstd"
        assert ic.inline_threshold == 512

    def test_compression_level_bounds(self):
        with pytest.raises(ValidationError):
            IcechunkConfig(compression_level=-1)  # ge=0
        with pytest.raises(ValidationError):
            IcechunkConfig(compression_level=23)  # le=22

    def test_invalid_algorithm(self):
        with pytest.raises(ValidationError):
            IcechunkConfig(compression_algorithm="snappy")

    def test_manifest_preload_defaults(self):
        ic = IcechunkConfig()
        assert ic.manifest_preload_enabled is False
        assert ic.manifest_preload_max_refs == 100_000_000


# ===================================================================
# CompressionConfig / ChunkStrategy
# ===================================================================


class TestCompressionConfig:
    def test_defaults(self):
        c = CompressionConfig()
        assert c.zlib is True
        assert c.complevel == 5

    def test_complevel_bounds(self):
        with pytest.raises(ValidationError):
            CompressionConfig(complevel=-1)
        with pytest.raises(ValidationError):
            CompressionConfig(complevel=10)


class TestChunkStrategy:
    def test_defaults(self):
        cs = ChunkStrategy()
        assert cs.epoch == 34560
        assert cs.sid == -1

    def test_epoch_must_be_positive(self):
        with pytest.raises(ValidationError):
            ChunkStrategy(epoch=0)


# ===================================================================
# SitesConfig
# ===================================================================


class TestSitesConfig:
    def test_empty_sites_warns(self):
        with pytest.warns(UserWarning, match="No research sites defined"):
            SitesConfig(sites={})

    def test_valid_site(self):
        sites = SitesConfig(
            sites={
                "rosalia": SiteConfig(
                    gnss_site_data_root="/data/rosalia",
                    receivers={
                        "c1": ReceiverConfig(type="canopy", directory="c1"),
                        "r1": ReceiverConfig(
                            type="reference", directory="r1", scs_from="all"
                        ),
                    },
                )
            }
        )
        assert "rosalia" in sites.sites


# ===================================================================
# CanvodConfig — top-level
# ===================================================================


class TestCanvodConfig:
    def test_extra_keys_forbidden(self):
        """CanvodConfig has extra='forbid' to catch typos."""
        with pytest.raises(ValidationError, match="extra"):
            CanvodConfig(
                processing=ProcessingConfig(
                    metadata=MetadataConfig(
                        author="A", email="a@b.com", institution="U"
                    ),
                    storage=StorageConfig(stores_root_dir=Path("/path/to/stores")),
                ),
                sites=SitesConfig(
                    sites={
                        "s": SiteConfig(
                            gnss_site_data_root="/data",
                            receivers={
                                "c": ReceiverConfig(type="canopy", directory="c"),
                                "r": ReceiverConfig(
                                    type="reference", directory="r", scs_from="all"
                                ),
                            },
                        )
                    }
                ),
                sids=SidsConfig(),
                typo_key="oops",  # <-- extra key
            )

    def test_nasa_earthdata_accessor(self):
        cfg = CanvodConfig(
            processing=ProcessingConfig(
                metadata=MetadataConfig(author="A", email="a@b.com", institution="U"),
                credentials=CredentialsConfig(nasa_earthdata_acc_mail="user@nasa.gov"),
                storage=StorageConfig(stores_root_dir=Path("/path/to/stores")),
            ),
            sites=SitesConfig(
                sites={
                    "s": SiteConfig(
                        gnss_site_data_root="/data",
                        receivers={
                            "c": ReceiverConfig(type="canopy", directory="c"),
                            "r": ReceiverConfig(
                                type="reference", directory="r", scs_from="all"
                            ),
                        },
                    )
                }
            ),
            sids=SidsConfig(),
        )
        assert cfg.nasa_earthdata_acc_mail == "user@nasa.gov"
