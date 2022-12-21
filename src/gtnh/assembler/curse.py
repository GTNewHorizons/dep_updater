"""Module handling curse pack assembling."""
import shutil
from json import dump
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from zipfile import ZipFile

import httpx
from colorama import Fore
from structlog import get_logger

from gtnh.assembler.downloader import get_asset_version_cache_location
from gtnh.assembler.generic_assembler import GenericAssembler
from gtnh.defs import CACHE_DIR, RELEASE_CURSE_DIR, ROOT_DIR, ModSource, Side
from gtnh.models.gtnh_config import GTNHConfig
from gtnh.models.gtnh_release import GTNHRelease
from gtnh.models.gtnh_version import GTNHVersion
from gtnh.models.mod_info import GTNHModInfo
from gtnh.modpack_manager import GTNHModpackManager

log = get_logger(__name__)


def is_valid_curse_mod(mod: GTNHModInfo, version: GTNHVersion) -> bool:
    """
    Tell if a given mod is a valid curseforge mod or not.

    Parameters
    ----------
    mod: GTNHModInfo
        The given mod.

    version: GTNHVersion
        The associated version to the mod.

    Returns
    -------
    True if it's a valid curseforge mod, False otherwise.
    """
    # If we don't have curse file info, it's not a valid curse file
    if version.curse_file is None:
        return False

    # If we don't have a file no, or a project no, it's not a valid curse file
    if not version.curse_file.file_no or not version.curse_file.project_no:
        return False

    return True


def is_mod_from_hidden_repo(mod: GTNHModInfo) -> bool:
    """
    Tell if a given mod is from a private GitHub repository.

    Parameters
    ----------
    mod: GTNHModInfo
        The given mod.

    Returns
    -------
    True if it's from a private repository, False otherwise.
    """
    if not mod.is_github():
        return False

    return mod.private


def is_mod_from_github(mod: GTNHModInfo) -> bool:
    """
    Tell if a mod is from GitHub.

    Parameters
    ----------
    mod: The given mod.

    Returns
    -------
    True if the mod is from GitHub, False otherwise.
    """
    return isinstance(mod, GTNHModInfo)


def get_maven_url(mod: GTNHModInfo, version: GTNHVersion) -> str:
    """
    Return the maven url for a GitHub mod.

    Parameters
    ----------
    mod: GTNHModInfo
        The given mod.

    version: GTNHVersion
        The corresponding version.

    Returns
    -------
    A string corresponding to the maven url.
    """
    if not isinstance(mod, GTNHModInfo):
        raise TypeError("Only github mods have a maven url")

    if mod.maven:
        base = mod.maven
    else:
        log.warn(f"Missing mod.maven for {mod.name}, trying fallback url.")
        base = f"http://jenkins.usrv.eu:8081/nexus/content/repositories/releases/com/github/GTNewHorizons/{mod.name}/"

    url: str = f"{base}{version.version_tag}/{mod.name}-{version.version_tag}.jar"

    return url


async def resolve_github_url(client: httpx.AsyncClient, mod: GTNHModInfo, version: GTNHVersion) -> str:
    """
    Check if maven download url is availiable.

    If not, falling back to GitHub. For now, it is reasonable, but we may hit the anonymous request quota limit if we
    have too much missing maven urls. Better not to rely too much on this.

    Parameters
    ----------
    client: httpx.AsyncClient
        The async client to make the requests.

    mod: GTNHModInfo
        The mod to get the GitHub url.

    version: GTNHVersion
        The corresponding version.


    Returns
    -------
    A string corresponding to the mod's GitHub URL.
    """
    url = get_maven_url(mod, version)
    if url:
        response: httpx.Response = await client.head(url)
        if response.status_code in {200, 204}:
            return url
    log.warn(f"Using fallback url, couldn't find {url}")
    assert version.browser_download_url
    return version.browser_download_url


class CurseAssembler(GenericAssembler):
    """Curseforge assembler class. Allows for the assembling of curse archives."""

    def __init__(
        self,
        gtnh_modpack: GTNHModpackManager,
        release: GTNHRelease,
        task_progress_callback: Optional[Callable[[float, str], None]] = None,
        global_progress_callback: Optional[Callable[[float, str], None]] = None,
        changelog_path: Optional[Path] = None,
    ):
        """
        Construct the CurseAssembler class.

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

        self.overrides_folder = Path("overrides")
        self.manifest_json = Path("manifest.json")
        self.dependencies_json = self.overrides_folder / "config" / "dependencies.json"
        self.tempfile = CACHE_DIR / "temp"
        self.overrides = ROOT_DIR / "overrides.png"
        self.overrideslash = ROOT_DIR / "overrideslash.png"

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
        return RELEASE_CURSE_DIR / f"GT_New_Horizons_{self.release.version}.zip"

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
        if side not in {Side.CLIENT}:
            raise Exception("Can only assemble release for CLIENT")

        # + 2 pictures in the overrides + manifest.json + dependencies.json
        delta_progress: float = 100 / (2 + self.get_amount_of_files_in_config(side) + 1 + 1)
        self.set_progress(delta_progress)

        archive_name: Path = self.get_archive_path(side)

        # deleting any existing archive
        if archive_name.exists():
            archive_name.unlink()
            log.warn(f"Previous archive {Fore.YELLOW}'{archive_name}'{Fore.RESET} deleted")

        log.info(f"Constructing {Fore.YELLOW}{side}{Fore.RESET} archive at {Fore.YELLOW}'{archive_name}'{Fore.RESET}")

        with ZipFile(self.get_archive_path(side), "w") as archive:
            log.info("Adding config to the archive")
            self.add_config(side, self.get_config(), archive, verbose=verbose)
            log.info("Adding manifest.json to the archive")
            self.generate_meta_data(side, archive)
            log.info("Adding dependencies.json to the archive")
            await self.generate_json_dep(side, archive)
            log.info("Adding overrides to the archive")
            self.add_overrides(side, archive)
            log.info("Archive created successfully!")

    def add_overrides(self, side: Side, archive: ZipFile) -> None:
        """
        Add the overrides to the curseforge archive.

        Parameters
        ----------
        side: Side
            Client side.

        archive: ZipFile
            The archive being assembled.

        Returns
        -------
        None.
        """
        archive.write(self.overrides, arcname=self.overrides_folder / "overrides.png")
        archive.write(self.overrideslash, arcname=self.overrides_folder / "overrideslash.png")
        coremod, coremod_version = [
            (mod, version) for mod, version in self.get_mods(side) if mod.name == "NewHorizonsCoreMod"
        ][0]
        source_file: Path = get_asset_version_cache_location(coremod, coremod_version)
        archive_path: Path = self.overrides_folder / "mods" / source_file.name
        archive.write(source_file, arcname=archive_path)

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

        with ZipFile(config_file, "r") as config_zip:

            for item in config_zip.namelist():
                if item in self.exclusions[side]:
                    continue
                with config_zip.open(item) as config_item:
                    with archive.open(
                        str(self.overrides_folder) + "/" + item, "w"
                    ) as target:  # can't use Path for the whole
                        # path here as it strips leading / but those are used by
                        # zipfile to know if it's a file or a folder. If used here,
                        # Path objects will lead to the creation of empty files for
                        # every folder.
                        shutil.copyfileobj(config_item, target)
                        if self.task_progress_callback is not None:
                            self.task_progress_callback(self.get_progress(), f"adding {item} to the archive")

        assert self.changelog_path
        self.add_changelog(archive, arcname=self.overrides_folder / self.changelog_path.name)

    async def generate_json_dep(self, side: Side, archive: ZipFile) -> None:
        """
        Generate the dependencies.json and put it in the archive.

        Parameters
        ----------
        side: Side
            Client side.

        archive: ZipFile
            The archive being assembled.

        Returns
        -------
        None.
        """
        mod_list: List[Tuple[GTNHModInfo, GTNHVersion]] = self.get_mods(side)
        mod: GTNHModInfo
        version: GTNHVersion
        dep_json: List[Dict[str, str]] = []
        with ZipFile(RELEASE_CURSE_DIR / "downloads.zip", "w") as file:
            async with httpx.AsyncClient(http2=True) as client:
                for mod, version in mod_list:
                    if mod.name == "NewHorizonsCoreMod" or is_valid_curse_mod(mod, version):
                        continue  # skipping it as it's in the overrides

                    url: Optional[str]
                    if mod.source == ModSource.github:
                        if not version.maven_url:
                            url = await resolve_github_url(client, mod, version)
                        else:
                            url = version.maven_url

                        # Hacky detection
                        if url and "jenkins.usrv.eu:8081" in url:
                            version.maven_url = url
                    else:
                        url = version.download_url

                    path: Path = get_asset_version_cache_location(mod, version)
                    file.write(path, arcname=path.name)
                    assert url
                    # url = f"http://downloads.gtnewhorizons.com/Mods_for_Twitch/{path.name}"  # temporary override until maven is fixed
                    mod_obj: Dict[str, str] = {"path": f"mods/{version.filename}", "url": url}

                    dep_json.append(mod_obj)

        with open(self.tempfile, "w") as temp:
            dump(dep_json, temp, indent=2)

        archive.write(self.tempfile, arcname=str(self.dependencies_json))
        if self.task_progress_callback is not None:
            self.task_progress_callback(self.get_progress(), f"adding {self.dependencies_json} to the archive")
        self.tempfile.unlink()

    def generate_meta_data(self, side: Side, archive: ZipFile) -> None:
        """
        Generate the manifest.json and place it in the archive.

        Parameters
        ----------
        side: Side
            CLient side.

        archive: ZipFile
            The archive being assembled.

        Returns
        -------
        None.
        """
        metadata = {
            "minecraft": {"version": "1.7.10", "modLoaders": [{"id": "forge-10.13.4.1614", "primary": True}]},
            "manifestType": "minecraftModpack",
            "manifestVersion": 1,
            "name": "GT New Horizons",
            "version": "{0}-1.7.10".format(self.release.version),
            "author": "DreamMasterXXL",
            "overrides": "overrides",
        }

        mod: GTNHModInfo
        version: GTNHVersion
        files = []
        for mod, version in self.get_mods(side):
            if is_valid_curse_mod(mod, version):
                assert version.curse_file  # make mypy happy
                # ignoring mypy errors here because it's all good in the check above
                files.append(
                    {"projectID": version.curse_file.project_no, "fileID": version.curse_file.file_no, "required": True}
                )

        metadata["files"] = files

        with open(self.tempfile, "w") as temp:
            dump(metadata, temp, indent=2)

        archive.write(self.tempfile, arcname=str(self.manifest_json))

        if self.task_progress_callback is not None:
            self.task_progress_callback(self.get_progress(), f"adding {self.manifest_json} to the archive")

        self.tempfile.unlink()
