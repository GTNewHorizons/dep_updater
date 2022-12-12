"""Module providing a ZipAssembler class for assembling zip archives in DAXXL."""
import shutil
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from zipfile import ZIP_DEFLATED, ZipFile

from structlog import get_logger

from gtnh.assembler.downloader import get_asset_version_cache_location
from gtnh.assembler.generic_assembler import GenericAssembler
from gtnh.defs import RELEASE_ZIP_DIR, SERVER_ASSETS_DIR, ServerBrand, Side
from gtnh.models.gtnh_config import GTNHConfig
from gtnh.models.gtnh_release import GTNHRelease
from gtnh.models.gtnh_version import GTNHVersion
from gtnh.models.mod_info import GTNHModInfo
from gtnh.modpack_manager import GTNHModpackManager

log = get_logger(__name__)


class ZipAssembler(GenericAssembler):
    """Zip assembler class. Allows for the assembling of zip archives."""

    def __init__(
        self,
        gtnh_modpack: GTNHModpackManager,
        release: GTNHRelease,
        task_progress_callback: Optional[Callable[[float, str], None]] = None,
        global_progress_callback: Optional[Callable[[float, str], None]] = None,
        changelog_path: Optional[Path] = None,
    ):
        """
        Construct the ZipAssembler class.

        Parameters
        ----------
        gtnh_modpack : GTNHModpackManager
            The modpack manager instance.

        release : GTNHRelease
            The target release object.

        task_progress_callback :  Optional[Callable[[float, str], None]]
            The callback to report the progress of the task if provided.

        global_progress_callback : Optional[Callable[[float, str], None]]
            The callback to report the global progress if provided.

        changelog_path : Optional[Path]
            The path to the changelog if provided.
        """
        GenericAssembler.__init__(
            self,
            gtnh_modpack=gtnh_modpack,
            release=release,
            task_progress_callback=task_progress_callback,
            global_progress_callback=global_progress_callback,
            changelog_path=changelog_path,
        )

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
        side : Side
            The side of the archive being assembled.

        mods : list[tuple[GTNHModInfo, GTNHVersion]]
            List of (mod info / version) being added to the assembled archive.

        archive : ZipFile
            The assembled archive.

        verbose : bool
            Boolean controlling if yes or no the assembling process should be verbose.

        Returns
        -------
        None.
        """
        for mod, version in mods:
            source_file: Path = get_asset_version_cache_location(mod, version)
            archive_path: Path = Path("mods") / source_file.name
            archive.write(source_file, arcname=archive_path)
            if self.task_progress_callback is not None:
                self.task_progress_callback(
                    self.get_progress(), f"adding mod {mod.name} : version {version.version_tag} to the archive"
                )

    def add_server_assets(self, archive: ZipFile, server_brand: ServerBrand) -> None:
        """
        Add server assets to the archive if it's a server side archive.

        Parameters
        ----------
        archive : ZipFile
            The assembled archive.

        server_brand : ServerBrand
            The type of server being used.

        Returns
        -------
        None.
        """
        assets = self.get_server_assets(server_brand)

        for asset in assets:
            archive.write(asset, arcname=asset.relative_to(SERVER_ASSETS_DIR / server_brand.value))
            if self.task_progress_callback is not None:
                self.task_progress_callback(self.get_progress(), f"adding server asset {asset.name} to the archive")

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
                    with archive.open(item, "w") as target:
                        shutil.copyfileobj(config_item, target)
                        if self.task_progress_callback is not None:
                            self.task_progress_callback(self.get_progress(), f"adding {item} to the archive")

        self.add_changelog(archive)

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
        return RELEASE_ZIP_DIR / f"GT_New_Horizons_{self.release.version}_{side}.zip"

    async def assemble(self, side: Side, verbose: bool = False, server_brand: ServerBrand = ServerBrand.forge) -> None:
        """
        Assemble the zip release.

        Parameters
        ----------
        side : Side
            The side of the archive being assembled.

        verbose : bool
            Boolean controlling if yes or no the assembling process should be verbose.

        server_brand : ServerBrand
            The type of server being used.

        Returns
        -------
        None.
        """
        # +1 for the changelog
        amount_of_files: int = len(self.get_mods(side)) + self.get_amount_of_files_in_config(side) + 1

        if side == Side.SERVER:
            amount_of_files += len(self.get_server_assets(server_brand))

        self.set_progress(100 / amount_of_files)
        await GenericAssembler.assemble(self, side, verbose)

        if side == Side.SERVER:
            log.info("Adding server assets to the server release.")
            with ZipFile(self.get_archive_path(side), "a") as archive:
                self.add_server_assets(archive, server_brand)

    @classmethod
    def get_server_assets(cls, server_brand: ServerBrand) -> List[Path]:
        """
        Return the list of Path objects corresponding to the server brand's assets.

        Parameters
        ----------
        server_brand : ServerBrand
            The type of server being used.

        Returns
        -------
        A list of paths representing the server assets corresponding to the server brand.
        """
        path_objects: List[Path] = [path_object for path_object in (SERVER_ASSETS_DIR / server_brand.value).iterdir()]

        assets: List[Path] = []
        folders: List[Path]

        while len(path_objects) > 0:
            assets.extend([file for file in path_objects if file.is_file()])

            folders = [folder for folder in path_objects if folder.is_dir()]
            path_objects = []
            for folder in folders:
                path_objects.extend([path for path in folder.iterdir()])

        return assets
