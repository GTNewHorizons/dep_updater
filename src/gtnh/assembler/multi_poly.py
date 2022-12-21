"""Module handling the MMC pack releases."""
import shutil
from pathlib import Path
from typing import Callable, Optional, Tuple
from zipfile import ZIP_DEFLATED, ZipFile

from gtnh.assembler.downloader import get_asset_version_cache_location
from gtnh.assembler.generic_assembler import GenericAssembler
from gtnh.defs import MMC_PACK_INSTANCE, MMC_PACK_JSON, RELEASE_MMC_DIR, Side
from gtnh.models.gtnh_config import GTNHConfig
from gtnh.models.gtnh_release import GTNHRelease
from gtnh.models.gtnh_version import GTNHVersion
from gtnh.models.mod_info import GTNHModInfo
from gtnh.modpack_manager import GTNHModpackManager


class MMCAssembler(GenericAssembler):
    """MMC assembler class. Allows for the assembling of mmc archives."""

    def __init__(
        self,
        gtnh_modpack: GTNHModpackManager,
        release: GTNHRelease,
        task_progress_callback: Optional[Callable[[float, str], None]] = None,
        global_progress_callback: Optional[Callable[[float, str], None]] = None,
        changelog_path: Optional[Path] = None,
    ):
        """
        Construct the MMCAssembler class.

        Parameters
        ----------
        gtnh_modpack: GTNHModpackManager
            The modpack manager instance.

        release: GTNHRelease
            The targetted release.

        task_progress_callback: Optional[Callable[[float, str], None]]
            The callback used to report progress within the task process.

        global_progress_callback: Optional[Callable[[float, str], None]]
            The callback used to report total progress.

        changelog_path: Optional[Path]
            The path of the changelog.
        """
        GenericAssembler.__init__(
            self,
            gtnh_modpack=gtnh_modpack,
            release=release,
            task_progress_callback=task_progress_callback,
            global_progress_callback=global_progress_callback,
            changelog_path=changelog_path,
        )
        self.mmc_archive_root: Path = Path(f"GT New Horizons {self.release.version}")
        self.mmc_modpack_files: Path = self.mmc_archive_root / ".minecraft"
        self.mmc_modpack_mods: Path = self.mmc_modpack_files / "mods"

    def add_mods(
        self,
        side: Side,
        mods: list[tuple[GTNHModInfo, GTNHVersion]],
        archive: ZipFile,
        verbose: bool = False,
    ) -> None:
        """
        Add mods to the archive being assembled.

        Parameters
        ----------
        side: Side
            The side of the archive being assembled.

        mods: list[tuple[GTNHModInfo, GTNHVersion]]
            List of (mod info / version) being added to the assembled archive.

        archive: ZipFile
            The assembled archive.

        verbose: bool
            Boolean controlling if yes or no the assembling process should be verbose.

        Returns
        -------
        None.
        """
        for mod, version in mods:
            source_file: Path = get_asset_version_cache_location(mod, version)
            archive_path: Path = self.mmc_modpack_mods / source_file.name
            archive.write(source_file, arcname=archive_path)
            if self.task_progress_callback is not None:
                self.task_progress_callback(
                    self.get_progress(), f"adding mod {mod.name} : version {version.version_tag} to the archive"
                )

    def add_config(
        self, side: Side, config: Tuple[GTNHConfig, GTNHVersion], archive: ZipFile, verbose: bool = False
    ) -> None:
        """
        Add config to the archive being assembled.

        Parameters
        ----------
        side : Side
            The side of the archive being assembled.

        config: Tuple[GTNHConfig, GTNHVersion]
            (config / version) couple used to determine config release used to assemble the pack.

        archive : ZipFile
            The assembled archive.

        verbose : bool
            Boolean controlling if yes or no the assembling process should be verbose.

        Returns
        -------
        None.
        """
        modpack_config: GTNHConfig
        config_version: Optional[GTNHVersion]
        modpack_config, config_version = config

        config_file: Path = get_asset_version_cache_location(modpack_config, config_version)

        with ZipFile(config_file, "r", compression=ZIP_DEFLATED) as config_zip:

            for item in config_zip.namelist():
                if item in self.exclusions[side]:
                    continue
                with config_zip.open(item) as config_item:
                    with archive.open(
                        str(self.mmc_modpack_files) + "/" + item, "w"
                    ) as target:  # can't use Path for the whole
                        # path here as it strips leading / but those are used by
                        # zipfile to know if it's a file or a folder. If used here,
                        # Path objects will lead to the creation of empty files for
                        # every folder.
                        shutil.copyfileobj(config_item, target)
                        if self.task_progress_callback is not None:
                            self.task_progress_callback(self.get_progress(), f"adding {item} to the archive")
        assert self.changelog_path
        self.add_changelog(archive, arcname=self.mmc_modpack_files / self.changelog_path.name)

    def get_archive_path(self, side: Side) -> Path:
        """
        Get the archive path for the release.

        Parameters
        ----------
        side : Side
            The side of the archive being assembled.

        Returns
        -------
        A Path object representing the archive's path.
        """
        return RELEASE_MMC_DIR / f"GT_New_Horizons_{self.release.version}_(MMC).zip"

    async def assemble(self, side: Side, verbose: bool = False) -> None:
        """
        Assemble the release.

        Parameters
        ----------
        side : Side
            The side of the archive being assembled.

        verbose : bool
            Boolean controlling if yes or no the assembling process should be verbose.

        Returns
        -------
        None.
        """
        if side != Side.CLIENT:
            raise ValueError(f"Only valid side is {Side.CLIENT}, got {side}")

        # +1 for the metadata file
        self.set_progress(100 / (len(self.get_mods(side)) + self.get_amount_of_files_in_config(side) + 1))
        await GenericAssembler.assemble(self, side, verbose)

        self.add_mmc_meta_data(side)

    def add_mmc_meta_data(self, side: Side) -> None:
        """
        Add additional metadata to the MMC archive.

        Parameters
        ----------
        side: Side
            Client side.

        Returns
        -------
        None.
        """
        with ZipFile(self.get_archive_path(side), "a") as archive:
            if self.task_progress_callback is not None:
                self.task_progress_callback(self.get_progress(), "adding archive's metadata to the archive")
            archive.writestr(str(self.mmc_archive_root) + "/mmc-pack.json", MMC_PACK_JSON)
            archive.writestr(
                str(self.mmc_archive_root) + "/instance.cfg", MMC_PACK_INSTANCE.format(f"GTNH {self.release.version}")
            )
