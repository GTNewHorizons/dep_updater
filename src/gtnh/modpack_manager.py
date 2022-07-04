import asyncio
import itertools
import json
import os
from pathlib import Path
from typing import Callable

from cache import AsyncLRU
from colorama import Fore, Style
from gidgethub import BadRequest
from gidgethub.httpx import GitHubAPI
from httpx import AsyncClient
from packaging.version import LegacyVersion
from retry import retry
from structlog import get_logger

from gtnh.assembler.downloader import get_asset_version_cache_location
from gtnh.defs import (
    AVAILABLE_ASSETS_FILE,
    BLACKLISTED_REPOS_FILE,
    GREEN_CHECK,
    GTNH_MODPACK_FILE,
    MAVEN_BASE_URL,
    OTHER,
    RED_CROSS,
    ROOT_DIR,
    UNKNOWN,
    Side,
)
from gtnh.exceptions import RepoNotFoundException
from gtnh.github.uri import latest_release_uri, org_repos_uri, repo_releases_uri, repo_uri
from gtnh.models.available_assets import AvailableAssets
from gtnh.models.gtnh_config import CONFIG_REPO_NAME
from gtnh.models.gtnh_modpack import GTNHModpack
from gtnh.models.gtnh_release import GTNHRelease, load_release, save_release
from gtnh.models.gtnh_version import version_from_release
from gtnh.models.mod_info import GTNHModInfo
from gtnh.models.versionable import Versionable, version_is_newer, version_sort_key
from gtnh.utils import AttributeDict, get_github_token

log = get_logger(__name__)

# Up Next - GT-New-Horizons-Modpack config/scripts handling


class GTNHModpackManager:
    """
    The GTNH ModPack Manager - Manages the GTNH Modpack
    """

    def __init__(self, client: AsyncClient) -> None:
        self.assets: AvailableAssets = self.load_assets()
        self.mod_pack: GTNHModpack = self.load_modpack()
        self.blacklisted_repos = self.load_blacklisted_repos()
        self.org = "GTNewHorizons"
        self.client = client
        self.gh = GitHubAPI(self.client, "DreamAssemblerXXL", oauth_token=get_github_token())

    @AsyncLRU(maxsize=None)  # type: ignore
    async def get_all_repos(self) -> dict[str, AttributeDict]:
        return {r["name"]: AttributeDict(r) async for r in self.gh.getiter(org_repos_uri(self.org))}

    @AsyncLRU(maxsize=None)  # type: ignore
    async def get_repo(self, name: str) -> AttributeDict:
        try:
            return AttributeDict(await self.gh.getitem(repo_uri(self.org, name)))
        except Exception:
            raise RepoNotFoundException(f"Repo not Found {name}")

    def add_release(self, release: GTNHRelease, update: bool = False) -> bool:
        log.info(f"Adding Release `{Fore.GREEN}{release.version}{Fore.RESET}`")
        if not update and release.version in self.mod_pack.releases:
            log.error(f"Release `{Fore.RED}{release.version}{Fore.RESET} already exists, and update was not specified!")
            return False

        self.mod_pack.releases |= {release.version}
        return save_release(release, update=update)

    def get_release(self, release_name: str) -> GTNHRelease | None:
        if release_name in self.mod_pack.releases:
            return load_release(release_name)

        return None

    async def update_all(self, mods_to_update: list[str] | None = None) -> None:
        if await self.update_available_assets(mods_to_update):
            self.save_assets()

    async def update_available_assets(self, assets_to_update: list[str] | None = None) -> bool:
        all_repos = await self.get_all_repos()

        tasks = []
        to_update: list[Versionable] = list(itertools.chain(self.assets.github_mods, [self.assets.config]))
        for asset in to_update:
            if assets_to_update and asset.name not in assets_to_update:
                continue

            repo = all_repos.get(asset.name)
            if not repo:
                log.error(f"{Fore.RED}Missing repo for {Fore.CYAN}{asset.name}{Fore.RED}, skipping update check.{Fore.RESET}")
                continue
            tasks.append(self.update_versionable_from_repo(asset, repo))

        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        return any([r for r in gathered])

    async def update_versionable_from_repo(self, versionable: Versionable, repo: AttributeDict) -> bool:
        """
        Attempt to update a versionable asset from a github repository.
        :param versionable: The asset to check for update
        :param repo: The repo corresponding to the asset
        :return: True if the asset, or any releases were updated; False otherwise
        """
        version_updated = False
        versionable_updated = False
        log.info(f"Checking {Fore.CYAN}{versionable.name}:{Fore.YELLOW}{versionable.latest_version}{Fore.RESET} for updates")
        latest_release = await self.get_latest_github_release(repo)

        latest_version = latest_release.tag_name if latest_release else "<unknown>"

        if version_is_newer(latest_version, versionable.latest_version):
            # Candidate update found
            version_updated = True
            log.info(f"Found candidate newer version for mod {Fore.CYAN}{versionable.name}:{Fore.YELLOW}{latest_version}{Fore.RESET}")

        if isinstance(versionable, GTNHModInfo):
            versionable_updated |= await self.update_github_mod_from_repo(versionable, repo)

        # Versionable
        if version_updated or not versionable.versions:
            versionable_updated |= await self.update_versions_from_repo(versionable, repo)

        if versionable_updated:
            log.info(f"Updated {Fore.CYAN}{versionable.name}{Fore.RESET}!")

        return versionable_updated

    async def update_github_mod_from_repo(self, mod: GTNHModInfo, repo: AttributeDict) -> bool:
        """
        Additional updates only applicable to a mod
        :param mod: The mod to check for update
        :param repo: The repo corresonding to the mod
        :return: True if the mod, or any releases were updated
        """
        mod_updated = False
        if mod.license in [UNKNOWN, OTHER]:
            mod_license = await self.get_license(repo)
            if mod_license is not None:
                log.info(f"Updated License: {mod_license}")
                mod.license = mod_license
                mod_updated = True

        if mod.repo_url is None:
            repo_url = repo.get("html_url")
            if repo_url:
                mod.repo_url = repo_url
                log.info(f"Updated Repo URL: {mod.repo_url}")
                mod_updated = True

        if mod.maven is None:
            maven = await self.get_maven(mod.name)
            if maven:
                mod.maven = maven
                log.info(f"Updated Maven: {mod.maven}")
                mod_updated = True

        if mod.private != repo.get("private"):
            mod.private = bool(repo.get("private"))
            log.info(f"Updated Private Repo Status: {mod.private}")
            mod_updated = True

        return mod_updated

    async def get_latest_github_release(self, repo: AttributeDict) -> AttributeDict | None:
        try:
            latest_release = AttributeDict(await self.gh.getitem(latest_release_uri(self.org, repo.name)))
        except BadRequest:
            log.error(f"{Fore.RED}No latest release found for {Fore.CYAN}{repo.get('name')}{Style.RESET_ALL}")
            latest_release = None

        return latest_release

    async def update_versions_from_repo(self, asset: Versionable, repo: AttributeDict) -> bool:
        releases = [AttributeDict(r) async for r in self.gh.getiter(repo_releases_uri(self.org, repo.name))]

        # Sorted releases, newest version first
        sorted_releases = sorted(releases, key=lambda r: LegacyVersion(r.tag_name), reverse=True)
        version_updated = False

        asset.versions = sorted(asset.versions, key=version_sort_key)

        for release in sorted_releases:
            if asset.has_version(release.tag_name):
                # We don't support updating of tagged versions, so if we see a version we already have, skip it
                # and the rest of the versions
                break

            version = version_from_release(release, asset.type)
            if not version:
                log.error(
                    f"{Fore.RED}No assets found for asset `{Fore.CYAN}{asset.name}{Fore.RESET}` release " f"`{release.tag_name}, skipping.{Style.RESET_ALL}"
                )
                continue

            if version_is_newer(version.version_tag, asset.latest_version):
                log.info(
                    f"Updating latest version for `{Fore.CYAN}{asset.name}{Fore.RESET}` "
                    f"{Style.DIM}{Fore.GREEN}{asset.latest_version}{Style.RESET_ALL} -> "
                    f"{Fore.GREEN}{version.version_tag}{Style.RESET_ALL}"
                )
                asset.latest_version = version.version_tag

            log.info(f"Adding version {Fore.GREEN}`{version.version_tag}`{Style.RESET_ALL} for asset " f"`{Fore.CYAN}{asset.name}{Fore.RESET}`")
            asset.add_version(version)
            version_updated = True

        return version_updated

    async def get_license(self, repo: AttributeDict) -> str | None:
        """
        Attempt to find a license for a mod, based on the repository; falling back to some manually collected licenses
        :param repo: Github Repository
        :return: License `str`
        """
        mod_license = None
        try:
            repo_license = repo.license
            if repo_license:
                mod_license = repo_license.license.name
                log.info(f"Found license `{Fore.YELLOW}{mod_license}{Fore.RESET}` from repo")
        except BadRequest:
            log.info("No license found from repo")

        if mod_license in [None, UNKNOWN, OTHER]:
            with open(ROOT_DIR / "licenses_from_boubou.json") as f:
                manual_licenses = json.loads(f.read())
                by_url = {v["url"]: v.get("license", None) for v in manual_licenses.values()}
                mod_license = by_url.get(repo.html_url, None)
                if mod_license:
                    log.info(f"Found fallback license {Fore.YELLOW}{mod_license}{Fore.RESET}.")

        if not mod_license:
            log.info("No license found!")

        return mod_license

    async def get_maven(self, mod_name: str) -> str | None:
        """
        Get the maven URL for a `mod_name`, ensuring it exists
        :param mod_name: Mod Name
        :return: Maven URL, if found
        """
        maven_url = MAVEN_BASE_URL + mod_name + "/"
        response = await self.client.head(maven_url, follow_redirects=True)

        if response.status_code == 200:
            return maven_url
        elif response.status_code >= 500:
            raise Exception(f"Maven unreachable status: {response.status_code}")

        return None

    async def generate_release(self, version: str, update_available: bool = True, overrides: dict[str, str] | None = None) -> GTNHRelease:
        if update_available:
            log.info("Updating assets")
            await self.update_all()

        log.info(f"Assembling release: `{Fore.GREEN}{version}{Fore.RESET}`")
        if overrides:
            log.info(f"Using overrides: `{Fore.GREEN}{overrides}{Fore.RESET}`")

        config = self.assets.config.latest_version
        github_mods: dict[str, str] = {}
        for mod in self.assets.github_mods:
            if mod.disabled:
                log.warn(f"Mod `{Fore.CYAN}{mod.name}{Fore.RESET}` is disabled, skipping")
                continue

            override = overrides and overrides.get(mod.name)
            mod_version = override if override else mod.latest_version

            if not mod.has_version(mod_version):
                log.warn(f"Version `{Fore.YELLOW}{mod_version}{Fore.RESET} not found for Mod `{Fore.CYAN}{mod.name}{Fore.RESET}`, skipping")
                continue

            overide_str = f"{Fore.RED} ** OVERRIDE **{Fore.RESET}" if override else ""
            log.info(f"Using `{Fore.CYAN}{mod.name}{Fore.RESET}:{Fore.YELLOW}{mod_version}{Fore.RESET}{overide_str}")
            github_mods[mod.name] = mod.latest_version
        external_mods: dict[str, str] = {}

        return GTNHRelease(version=version, config=config, github_mods=github_mods, external_mods=external_mods)

    async def add_github_mod(self, name: str) -> GTNHModInfo | None:
        """
        Attempts to add a mod from a github repo
        :param name: Name of the github repo
        :return: The ModInfo, if any, that was created
        """
        log.info(f"Trying to add `{name}`.")

        new_repo = await self.get_repo(name)
        if self.assets.has_github_mod(new_repo.name):
            log.info(f"Mod `{name}` already exists.")
            return None

        new_mod = await self.mod_from_repo(new_repo)
        self.assets.add_github_mod(new_mod)

        del self.assets._github_modmap

        log.info(f"Successfully added {name}!")
        return new_mod

    async def mod_from_repo(self, repo: AttributeDict, side: Side = Side.BOTH) -> GTNHModInfo:
        try:
            latest_release = await self.get_latest_github_release(repo)
            latest_version = latest_release.tag_name if latest_release else "<unknown>"
        except Exception:
            latest_version = "<unknown>"

        mod = GTNHModInfo(
            name=repo.name,
            license=await self.get_license(repo),
            repo_url=repo.html_url,
            maven=await self.get_maven(repo.name),
            side=side,
            latest_version=latest_version,
            private=repo.private,
        )

        await self.update_versions_from_repo(mod, repo)

        mod.latest_version = latest_version

        return mod

    def load_assets(self) -> AvailableAssets:
        """
        Load the Available Mods manifest
        """
        log.info(f"Loading mods from {self.gtnh_asset_manifest_path}")
        with open(self.gtnh_asset_manifest_path, encoding="utf-8") as f:
            return AvailableAssets.parse_raw(f.read())

    def load_modpack(self) -> GTNHModpack:
        """
        Load the GTNH Modpack manifest
        """
        log.info(f"Loading GTNH Modpack from {self.modpack_manifest_path}")
        with open(self.modpack_manifest_path, encoding="utf-8") as f:
            return GTNHModpack.parse_raw(f.read())

    def save_assets(self) -> None:
        """
        Saves the Available Mods Manifest
        """
        log.info(f"Saving assets to from {self.gtnh_asset_manifest_path}")
        dumped = self.assets.json(exclude={"_github_modmap", "_external_modmap"}, exclude_unset=True, exclude_none=True, exclude_defaults=True)
        if dumped:
            with open(self.gtnh_asset_manifest_path, "w", encoding="utf-8") as f:
                f.write(dumped)
        else:
            log.error("Save aborted, empty save result")

    def load_blacklisted_repos(self) -> set[str]:
        with open(self.repo_blacklist_path) as f:
            return set(json.loads(f.read()))

    async def get_missing_repos(self) -> set[str]:
        """
        Return the list of mod repositories that are on github, not blacklisted, and not included in github_mods
        :param all_repos: A dictionary of [repo_name, Repository]
        :return: Set of repo names missing
        """
        all_repo_names = set((await self.get_all_repos()).keys())
        all_github_mod_names = set(self.assets._github_modmap.keys())
        config_repo = CONFIG_REPO_NAME
        return all_repo_names - all_github_mod_names - self.blacklisted_repos - {config_repo}

    def get_missing_mavens(self) -> set[str]:
        """
        Return the list of github mods that are missing a maven
        :return: Set of repo anmes missing mavens
        """
        all_github_mod_names = set(k for k, v in self.assets._github_modmap.items() if v.maven is None)

        return all_github_mod_names

    @property
    def gtnh_asset_manifest_path(self) -> Path:
        """
        Helper property for the available mods manifest file location
        """
        return ROOT_DIR / AVAILABLE_ASSETS_FILE

    @property
    def modpack_manifest_path(self) -> Path:
        return ROOT_DIR / GTNH_MODPACK_FILE

    @property
    def repo_blacklist_path(self) -> Path:
        """
        Helper property for the blacklisted repo file location
        """
        return ROOT_DIR / BLACKLISTED_REPOS_FILE

    @retry(delay=5, tries=3)
    async def download_asset(self, asset: Versionable, asset_version: str | None = None, is_github: bool = False) -> Path | None:
        if asset_version is None:
            asset_version = asset.latest_version

        type = "Github" if is_github else "External"
        version = asset.get_version(asset_version)
        if not version or not version.filename or not version.download_url:
            log.error(
                f"{RED_CROSS} {Fore.RED}Version `{Fore.YELLOW}{asset_version}{Fore.RED}` not found for {type} Asset "
                f"`{Fore.CYAN}{asset.name}{Fore.RED}`{Fore.RESET}"
            )
            return None

        private_repo = f" {Fore.MAGENTA}<PRIVATE REPO>{Fore.RESET}" if asset.private else ""

        log.info(
            f"Downloading {type} Asset `{Fore.CYAN}{asset.name}:{Fore.YELLOW}{asset_version}{Fore.RESET}` from {version.browser_download_url}{private_repo}"
        )

        mod_filename = get_asset_version_cache_location(asset, version)

        if os.path.exists(mod_filename):
            log.info(f"{Fore.YELLOW}Skipping re-redownload of {mod_filename}{Fore.RESET}")
            return mod_filename

        headers = {"Accept": "application/octet-stream"}
        if is_github:
            headers |= {"Authorization": f"token {get_github_token()}"}

        async with self.client.stream(url=version.download_url, headers=headers, method="GET", follow_redirects=True) as r:
            r.raise_for_status()
            with open(mod_filename, "wb") as f:
                async for chunk in r.aiter_bytes(chunk_size=8192):
                    f.write(chunk)
        log.info(f"{GREEN_CHECK} Download successful `{mod_filename}`")

        return mod_filename

    async def download_release(self, release: GTNHRelease, callback: Callable[[float, str], None] | None = None) -> list[Path]:
        """
        method to download all the mods required for a release of the pack

        :param mod_manager: The Modpack Manager
        :param release: Release to download
        :param callback: Callable that takes a float and a string in parameters. (mainly the method to update the
                    progress bar that takes a progress step per call and the label used to display infos to the user)
        :return: a list holding all the paths to the clientside mods and a list holding all the paths to the serverside
                mod.
        """

        log.info(f"Downloading mods for Release `{Fore.LIGHTYELLOW_EX}{release.version}{Fore.RESET}`")

        # computation of the progress per mod for the progressbar
        delta_progress = 100 / (len(release.github_mods) + len(release.external_mods))

        log.info(f"Downloading {Fore.GREEN}{len(release.github_mods)}{Fore.RESET} Github Mod(s)")
        # download of the github mods
        downloaders = []
        for mod_name, mod_version in release.github_mods.items():
            mod = self.assets.get_github_mod(mod_name)

            if callback is not None:
                callback(delta_progress, f"downloading github mods. current mod: {mod.name} Progress: {{0}}%")

            downloaders.append(self.download_asset(mod, mod_version, is_github=True))

        downloaders.append(self.download_asset(self.assets.config, release.config, is_github=True))

        for mod_name, mod_version in release.external_mods.items():
            mod = self.assets.get_external_mod(mod_name)
            if callback is not None:
                callback(delta_progress, f"downloading external mods. current mod: {mod.name} Progress: {{0}}%")

            # do the actual work
            downloaders.append(self.download_asset(mod, mod_version, is_github=False))

        downloaded: list[Path] = [d for d in await asyncio.gather(*downloaders) if d is not None]

        return downloaded
