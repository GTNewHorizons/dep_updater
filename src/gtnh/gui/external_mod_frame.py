import asyncio
from datetime import datetime
from tkinter import END, Button, Entry, IntVar, Label, LabelFrame, Listbox, Radiobutton, Scrollbar, StringVar, Toplevel
from tkinter.messagebox import showerror, showinfo, showwarning
from typing import Any, Callable, Coroutine, Dict, List, Optional

from gtnh.defs import ModSource, Position, Side
from gtnh.gui.mod_info_frame import ModInfoFrame
from gtnh.models import versionable
from gtnh.models.gtnh_version import GTNHVersion
from gtnh.models.mod_info import ExternalModInfo
from gtnh.modpack_manager import GTNHModpackManager


class ExternalModList(LabelFrame):
    """Widget handling the list of external mods."""

    def __init__(
        self, master: Any, frame_name: str, callbacks: Dict[str, Any], width: Optional[int] = None, **kwargs: Any
    ):
        """
        Constructor of the ExternalModList class.

        :param master: the parent widget
        :param frame_name: the name displayed in the framebox
        :param callbacks: a dict of callbacks passed to this instance
        :param width: the width to harmonize widgets in characters
        :param kwargs: params to init the parent class
        """
        LabelFrame.__init__(self, master, text=frame_name, **kwargs)
        self.ypadding: int = 0
        self.xpadding: int = 0

        self.btn_add_text: str = "Add new mod"
        self.btn_add_version_text: str = "Add new version to highlighted"
        self.btn_rem_text: str = "Delete highlighted"

        self.get_gtnh_callback: Callable[[], Coroutine[Any, Any, GTNHModpackManager]] = callbacks["get_gtnh"]
        self.get_external_mods_callback: Callable[[], Dict[str, str]] = callbacks["get_external_mods"]
        self.toggle_freeze: Callable[[], None] = callbacks["freeze"]
        self.mod_info_callback: Callable[[Any], None] = callbacks["mod_info"]
        self.add_mod_to_memory: Callable[[str, str], None] = callbacks["add_mod_in_memory"]
        self.del_mod_from_memory: Callable[[str], None] = callbacks["del_mod_in_memory"]

        self.width: int = (
            width
            if width is not None
            else max(len(self.btn_add_text), len(self.btn_rem_text), len(self.btn_add_version_text))
        )

        self.sv_repo_name: StringVar = StringVar(self, value="")

        self.lb_mods: Listbox = Listbox(self, exportselection=False)
        self.lb_mods.bind("<<ListboxSelect>>", lambda event: asyncio.ensure_future(self.on_listbox_click(event)))

        self.btn_add: Button = Button(
            self, text=self.btn_add_text, command=lambda: asyncio.ensure_future(self.add_external_mod())
        )

        self.btn_add_version: Button = Button(
            self, text=self.btn_add_version_text, command=lambda: asyncio.ensure_future(self.add_new_version())
        )

        self.btn_rem: Button = Button(
            self, text=self.btn_rem_text, command=lambda: asyncio.ensure_future(self.del_external_mod())
        )

        self.scrollbar: Scrollbar = Scrollbar(self)
        self.lb_mods.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.configure(command=self.lb_mods.yview)

    def configure_widgets(self) -> None:
        """
        Method to configure the widgets.

        :return: None
        """
        self.btn_add.configure(width=self.width)
        self.btn_add_version.configure(width=self.width)
        self.btn_rem.configure(width=self.width)

    def set_width(self, width: int) -> None:
        """
        Method to set the widgets' width.

        :param width: the new width
        :return: None
        """
        self.width = width
        self.configure_widgets()

    def get_width(self) -> int:
        """
        Getter for self.width.

        :return: the width in character sizes of the normalised widgets
        """
        return self.width

    def update_widget(self) -> None:
        """
        Method to update the widget and all its childs

        :return: None
        """
        self.hide()
        self.configure_widgets()
        self.show()

    def hide(self) -> None:
        """
        Method to hide the widget and all its childs
        :return None:
        """
        self.lb_mods.grid_forget()
        self.scrollbar.grid_forget()
        self.btn_add.grid_forget()
        self.btn_add_version.grid_forget()
        self.btn_rem.grid_forget()

        self.update_idletasks()

    def show(self) -> None:
        """
        Method used to display widgets and child widgets, as well as to configure the "responsiveness" of the widgets.

        :return: None
        """
        x: int = 0
        y: int = 0
        rows: int = 4
        columns: int = 2

        for i in range(rows):
            self.rowconfigure(i, weight=1, pad=self.xpadding)

        for i in range(columns):
            self.columnconfigure(i, weight=1, pad=self.ypadding)

        self.lb_mods.grid(row=x, column=y, columnspan=2, sticky=Position.HORIZONTAL)
        self.scrollbar.grid(row=x, column=y + 2, sticky=Position.VERTICAL)
        self.btn_add.grid(row=x + 1, column=y)
        self.btn_rem.grid(row=x + 1, column=y + 1, columnspan=2)
        self.btn_add_version.grid(row=x + 2, column=y)

        self.update_idletasks()

    async def add_new_version(self) -> None:
        """
        Method called when the button to add a new version to an external mod is pressed.

        :return: None
        """
        try:
            index: int = self.lb_mods.curselection()[0]
            mod_name: str = self.lb_mods.get(index)
            self.toggle_freeze()
            top_level: Toplevel = Toplevel(self)
            top_level.protocol("WM_DELETE_WINDOW", lambda: (self.toggle_freeze(), top_level.destroy()))  # type: ignore
            callbacks = {"get_gtnh": self.get_gtnh_callback}
            mod_addition_frame: ModAdditionFrame = ModAdditionFrame(
                top_level, "external version adder", callbacks=callbacks, mod_name=mod_name
            )
            mod_addition_frame.grid()
            mod_addition_frame.update_widget()
            top_level.title("External mod addition")
        except IndexError:
            showerror(
                "No curseforge mod selected",
                "In order to add a new version to a curseforge mod, you must select one first",
            )
            return

    async def del_external_mod(self) -> None:
        """
        Method called when the button to delete the highlighted external mod is pressed.

        :return: None
        """
        showerror("Feature not yet implemented", "The removal of external mods from assets is not yet implemented.")
        # don't forget to use self.del_mod_from_memory when implementing this

    async def add_external_mod(self) -> None:
        """
        Method called when the button to add an external mod is pressed.

        :return: None
        """
        # showerror("Feature not yet implemented", "The addition of external mods to the assets is not yet implemented.")
        # don't forget to use self.add_mod_in_memory when implementing this
        self.toggle_freeze()
        top_level: Toplevel = Toplevel(self)
        top_level.protocol("WM_DELETE_WINDOW", lambda: (self.toggle_freeze(), top_level.destroy()))  # type: ignore
        callbacks = {"get_gtnh": self.get_gtnh_callback}
        mod_addition_frame: ModAdditionFrame = ModAdditionFrame(top_level, "external mod adder", callbacks=callbacks)
        mod_addition_frame.grid()
        mod_addition_frame.update_widget()
        top_level.title("External mod addition")

    def populate_data(self, data: Any) -> None:
        """
        Method called by parent class to populate data in this class.

        :param data: the data to pass to this class
        :return: None
        """

        self.lb_mods.insert(END, *sorted(data))

    async def on_listbox_click(self, _: Any) -> None:
        """
        Callback used when the user clicks on the external mods' listbox.

        :param _: the tkinter event passed by the tkinter in the Callback (unused)
        :return: None
        """

        index: int = self.lb_mods.curselection()[0]
        gtnh: GTNHModpackManager = await self.get_gtnh_callback()
        mod_info: ExternalModInfo = gtnh.assets.get_external_mod(self.lb_mods.get(index))
        name: str = mod_info.name
        mod_versions: list[GTNHVersion] = mod_info.versions
        latest_version: Optional[GTNHVersion] = mod_info.get_latest_version()
        assert latest_version
        external_mods: Dict[str, str] = self.get_external_mods_callback()
        current_version: str = external_mods[name] if name in external_mods else latest_version.version_tag

        _license: str = mod_info.license or "No license detected"
        side: str = mod_info.side

        data = {
            "name": name,
            "versions": [version.version_tag for version in mod_versions],
            "current_version": current_version,
            "license": _license,
            "side": side,
        }
        self.mod_info_callback(data)


class ExternalModFrame(LabelFrame):
    """Main frame widget for the external mods' management."""

    def __init__(
        self, master: Any, frame_name: str, callbacks: Dict[str, Any], width: Optional[int] = None, **kwargs: Any
    ):
        """
        Constructor of the ExternalModFrame class.

        :param master: the parent widget
        :param frame_name: the name displayed in the framebox
        :param callbacks: a dict of callbacks passed to this instance
        :param width: the width to harmonize widgets in characters
        :param kwargs: params to init the parent class
        """
        self.ypadding: int = 0
        self.xpadding: int = 0
        LabelFrame.__init__(self, master, text=frame_name, **kwargs)

        self.width: Optional[int] = width

        mod_info_callbacks: Dict[str, Any] = {
            "set_mod_version": callbacks["set_external_mod_version"],
            "set_mod_side": callbacks["set_external_mod_side"],
        }
        self.mod_info_frame: ModInfoFrame = ModInfoFrame(
            self, frame_name="External mod info", callbacks=mod_info_callbacks
        )

        external_mod_list_callbacks: Dict[str, Any] = {
            "get_gtnh": callbacks["get_gtnh"],
            "get_external_mods": callbacks["get_external_mods"],
            "mod_info": self.mod_info_frame.populate_data,
            "add_mod_in_memory": callbacks["add_mod_in_memory"],
            "del_mod_in_memory": callbacks["del_mod_in_memory"],
            "freeze": callbacks["freeze"],
        }

        self.external_mod_list: ExternalModList = ExternalModList(
            self, frame_name="External mod list", callbacks=external_mod_list_callbacks
        )

        if self.width is None:
            self.width = self.external_mod_list.get_width()
            self.mod_info_frame.set_width(self.width)
            self.update_widget()

        else:
            self.mod_info_frame.set_width(self.width)
            self.external_mod_list.set_width(self.width)

    def configure_widgets(self) -> None:
        """
        Method to configure the widgets.

        :return: None
        """
        self.mod_info_frame.configure_widgets()
        self.external_mod_list.configure_widgets()

    def set_width(self, width: int) -> None:
        """
        Method to set the widgets' width.

        :param width: the new width
        :return: None
        """
        self.width = width
        self.mod_info_frame.set_width(self.width)
        self.external_mod_list.set_width(self.width)

    def get_width(self) -> int:
        """
        Getter for self.width.

        :return: the width in character sizes of the normalised widgets
        """
        assert self.width  # can't be None because how it's defined in the constructor
        return self.width

    def update_widget(self) -> None:
        """
        Method to update the widget and all its childs

        :return: None
        """
        self.hide()
        self.configure_widgets()
        self.show()

        self.external_mod_list.update_widget()
        self.mod_info_frame.update_widget()

    def hide(self) -> None:
        """
        Method to hide the widget and all its childs
        :return None:
        """
        self.external_mod_list.grid_forget()
        self.mod_info_frame.grid_forget()

        self.external_mod_list.hide()
        self.mod_info_frame.hide()

        self.update_idletasks()

    def show(self) -> None:
        """
        Method used to display widgets and child widgets, as well as to configure the "responsiveness" of the widgets.

        :return: None
        """
        x: int = 0
        y: int = 0
        rows: int = 2
        columns: int = 1

        for i in range(rows):
            self.rowconfigure(i, weight=1, pad=self.xpadding)

        for i in range(columns):
            self.columnconfigure(i, weight=1, pad=self.ypadding)

        self.external_mod_list.grid(row=x, column=y)
        self.mod_info_frame.grid(row=x + 1, column=y)

        self.external_mod_list.show()
        self.mod_info_frame.show()

        self.update_idletasks()

    def populate_data(self, data: Any) -> None:
        """
        Method called by parent class to populate data in this class.

        :param data: the data to pass to this class
        :return: None
        """
        mod_list: List[str] = data["external_mod_list"]
        self.external_mod_list.populate_data(mod_list)


class ModAdditionFrame(LabelFrame):
    """
    Class handling the widgets for the toplevel window about the mod addition.
    """

    def __init__(
        self,
        master: Any,
        frame_name: str,
        callbacks: Dict[str, Any],
        width: Optional[int] = None,
        mod_name: Optional[str] = None,
        **kwargs: Any,
    ):
        """
        Constructor of the ModAdditionFrame class.

        :param master: the parent widget
        :param frame_name: the name displayed in the framebox
        :param callbacks: a dict of callbacks passed to this instance
        :param width: the width to harmonize widgets in characters
        :param mod_name: optional parameter passed to this class if the mod exists already in DAXXL.
        :param kwargs: params to init the parent class
        """
        self.ypadding: int = 0
        self.xpadding: int = 0
        LabelFrame.__init__(self, master, text=frame_name, **kwargs)

        self.get_gtnh_callback: Callable[[], Coroutine[Any, Any, GTNHModpackManager]] = callbacks["get_gtnh"]

        self.width: int = width or 50

        self.add_version_only = mod_name is not None
        self.add_mod_and_version = mod_name is None

        self.mod_name = mod_name

        self.label_source_text: str = "Choose a source type for the mod"
        self.btn_src_other_text: str = "Other"
        self.btn_src_curse_text: str = "CurseForge"

        self.int_var_src: IntVar = IntVar()
        self.int_var_src.set(1)

        self.label_source: Label = Label(self, text=self.label_source_text)
        self.btn_src_other: Radiobutton = Radiobutton(
            self, text=self.btn_src_other_text, variable=self.int_var_src, value=2, command=self.update_widget
        )
        self.btn_src_curse: Radiobutton = Radiobutton(
            self, text=self.btn_src_curse_text, variable=self.int_var_src, value=1, command=self.update_widget
        )

        self.label_name_text: str = "Mod name:"
        self.label_name: Label = Label(self, text=self.label_name_text)
        self.sv_name: StringVar = StringVar(self)
        self.entry_mod_name: Entry = Entry(self, textvariable=self.sv_name)

        self.label_version_text: str = "Mod version:"
        self.label_version: Label = Label(self, text=self.label_version_text)
        self.sv_version: StringVar = StringVar(self)
        self.entry_version: Entry = Entry(self, textvariable=self.sv_version)

        self.label_download_link_text: str = "Download link (check your download history to get it):"
        self.label_download_link: Label = Label(self, text=self.label_download_link_text)

        self.label_cf_project_id_text: str = "project ID"
        self.label_cf_project_id: Label = Label(self, text=self.label_cf_project_id_text)

        self.sv_cf_project_id: StringVar = StringVar(self)
        self.entry_cf_project_id: Entry = Entry(self, textvariable=self.sv_cf_project_id)

        self.label_browser_url_text: str = "browser download page url (page where you can download the file):"
        self.label_browser_url: Label = Label(self, text=self.label_browser_url_text)

        self.sv_browser_url: StringVar = StringVar(self)
        self.entry_browser_url: Entry = Entry(self, textvariable=self.sv_browser_url)

        self.sv_download_link: StringVar = StringVar(self)
        self.entry_download_link: Entry = Entry(self, textvariable=self.sv_download_link)

        self.label_license_text = "Mod License"
        self.label_license: Label = Label(self, text=self.label_license_text)

        self.sv_license: StringVar = StringVar(self)
        self.entry_license: Entry = Entry(self, textvariable=self.sv_license)

        self.label_project_url_text: str = "Project url (page explaining the mod)"
        self.label_project_url: Label = Label(self, text=self.label_project_url_text)

        self.sv_project_url: StringVar = StringVar(self)
        self.entry_project_url: Entry = Entry(self, textvariable=self.sv_project_url)

        self.btn_add_text: str = "Add external mod to DreamAssemblerXXL"
        self.btn_add: Button = Button(
            self, text=self.btn_add_text, command=lambda: asyncio.ensure_future(self.add_mod())
        )

        if self.add_version_only:
            asyncio.ensure_future(self.set_mod_source())

    async def set_mod_source(self) -> None:
        """
        method used to set up the intvar corresponding to the source of the mod when it's just a mod version added.

        :return: None
        """
        gtnh: GTNHModpackManager = await self.get_gtnh_callback()

        # mod exists because the name is from the availiable mods in the assets.
        src = 1 if gtnh.assets.get_external_mod(self.mod_name).source == ModSource.curse else 2  # type: ignore
        self.int_var_src.set(src)

    def check_inputs(self) -> Dict[str, bool]:
        """
        Method used to check the inputs in the gui.

        :return: a dict with the tests as key and the value of the tests as values
        """
        name: str = self.mod_name if self.mod_name is not None else self.sv_name.get()
        version: str = self.sv_version.get()
        download_url: str = self.entry_download_link.get()
        project_id = self.entry_cf_project_id.get()
        browser_url = self.entry_browser_url.get()
        license = self.entry_license.get()
        project_url = self.entry_project_url.get()

        check_results: Dict[str, bool] = {
            "name": False,
            "version": False,
            "download_url": False,
            "project_id": False,
            "browser_url": False,
            "license": False,
            "project_url": False,
        }

        if name != "":
            check_results["name"] = True

        if version != "":
            check_results["version"] = True

        if license != "":
            check_results["license"] = True

        if download_url.endswith(".jar") and (
            download_url.startswith("http://") or download_url.startswith("https://")
        ):
            check_results["download_url"] = True

        if project_url.startswith("http://") or project_url.startswith("https://"):
            check_results["project_url"] = True

        if browser_url.startswith("http://") or browser_url.startswith("https://"):
            check_results["browser_url"] = True

        try:
            int(project_id)
            check_results["project_id"] = True
        except ValueError:
            pass

        if download_url.startswith("http://") or download_url.startswith("https://"):
            check_results["download_url"] = True

        return check_results

    async def add_mod(self) -> None:
        """
        Method to add an external mod to DAXXL.

        :return: None
        """
        error_messages = {
            "name": "Mod name is empty",
            "version": "Version is empty",
            "project_id": "The project id contains other characters than numbers",
            "download_url": "The download url isn't a valid http(s) link or isn't ending with '.jar'. Make sure you use the correct download link",
            "browser_url": "The browser download page link isn't a valid http(s) link or doesn't terminate by a number. Make sure you use the correct link.",
            "license": "missing license",
        }

        validation = self.check_inputs()

        not_curse_src: bool = self.int_var_src.get() != 1
        curse_src: bool = self.int_var_src.get() == 1

        blacklist_external_source: List[str] = ["project_id"]
        blacklist_external_source_new_version: List[str] = ["project_id", "project_url"]
        blacklist_curse_new_version: List[str] = ["project_id", "project_url"]
        blacklist_curse: List[str] = []
        only_mod: bool = self.add_version_only
        only_mod_external: bool = self.add_version_only and not_curse_src
        only_mod_curse: bool = self.add_version_only and curse_src
        external_mod: bool = not self.add_version_only and not_curse_src
        curse_mod: bool = not self.add_version_only and curse_src

        blacklist: List[str]

        if only_mod_external:  # new mod version for external source
            blacklist = blacklist_external_source_new_version
        elif only_mod_curse:  # new mod version for curse source
            blacklist = blacklist_curse_new_version
        elif external_mod:  # new mod for external source
            blacklist = blacklist_external_source
        elif curse_mod:
            blacklist = blacklist_curse
        else:
            raise NotImplementedError(
                "something went wrong during the addition of a new curse mod: unsupported mod type."
            )

        error_list = [error_messages[key] for key, value in validation.items() if not value and key not in blacklist]

        if error_list:
            showerror(
                "Error",
                "There was the following errors while trying to add a new external mod:\n- " + "\n- ".join(error_list),
            )
            return

        else:
            gtnh = await self.get_gtnh_callback()

            name: str = self.mod_name if only_mod else self.sv_name.get()  # type: ignore

            if gtnh.assets.has_external_mod(name) and self.add_mod_and_version:
                showwarning("Mod already existing", f"the mod {name} already exists in the database.")
                return

            version: str = self.sv_version.get()
            download_url: str = self.entry_download_link.get()
            browser_url = self.entry_browser_url.get()

            mod_version: GTNHVersion = GTNHVersion(
                version_tag=version,
                changelog="",
                prerelease=False,
                tagged_at=datetime.now(),
                filename=download_url.split("/")[-1],
                download_url=download_url,
                browser_download_url=browser_url,
            )
            mod: ExternalModInfo
            # adding mod
            if self.add_mod_and_version:
                license: str = self.entry_license.get()
                project_url: str = self.entry_project_url.get()
                project_id: str = self.entry_cf_project_id.get()

                mod = ExternalModInfo(
                    latest_version=version,
                    name=name,
                    license=license,
                    repo_url=None,
                    maven=None,
                    side=Side.BOTH,
                    source=ModSource.curse if curse_src else ModSource.other,
                    disabled=False,
                    external_url=project_url,
                    project_id=project_id if curse_src else None,
                    slug=None,
                    versions=[mod_version],
                )
                gtnh.assets.add_external_mod(mod)
                gtnh.save_assets()

            # adding version
            else:
                mod = gtnh.assets.get_external_mod(name)

                # if mod has already that version
                if mod.has_version(mod_version.version_tag):
                    showerror(
                        "Version already present",
                        f"Mod version {mod_version.version_tag} already exists in {mod}'s version list!",
                    )
                    return

                mod.add_version(mod_version)

                # updating latest version
                if versionable.version_is_newer(mod_version.version_tag, mod.latest_version):
                    mod.latest_version = mod_version.version_tag

                gtnh.save_assets()

            if self.add_version_only:
                showinfo(
                    "Version added successfully!",
                    f"Mod version {mod_version.version_tag} has been successfully added to {mod}'s version!",
                )
            else:
                showinfo("Mod added successfully!", f"Mod {mod.name} has been successfully added!")

    def configure_widgets(self) -> None:
        """
        Method to configure the widgets.

        :return: None
        """
        self.label_name.configure(width=self.width)
        self.entry_mod_name.configure(width=2 * self.width)
        self.label_version.configure(width=self.width)
        self.entry_version.configure(width=2 * self.width)

        self.label_source.configure(width=self.width)
        self.btn_src_other.configure(width=self.width)
        self.btn_src_curse.configure(width=self.width)
        self.label_download_link.configure(width=self.width)
        self.entry_download_link.configure(width=2 * self.width)

        self.label_cf_project_id.configure(width=self.width)
        self.entry_cf_project_id.configure(width=2 * self.width)
        self.label_browser_url.configure(width=self.width)
        self.entry_browser_url.configure(width=2 * self.width)
        self.btn_add.configure(width=self.width)
        self.label_license.configure(width=self.width)
        self.entry_license.configure(width=2 * self.width)

        self.label_project_url.configure(width=self.width)
        self.entry_project_url.configure(width=2 * self.width)

    def set_width(self, width: int) -> None:
        """
        Method to set the widgets' width.

        :param width: the new width
        :return: None
        """
        self.width = width
        self.configure_widgets()

    def get_width(self) -> int:
        """
        Getter for self.width.

        :return: the width in character sizes of the normalised widgets
        """
        return self.width

    def update_widget(self) -> None:
        """
        Method to update the widget and all its childs

        :return: None
        """
        self.hide()
        self.configure_widgets()
        self.show()

    def hide(self) -> None:
        """
        Method to hide the widget and all its childs
        :return None:
        """
        self.label_name.grid_forget()
        self.entry_mod_name.grid_forget()
        self.label_version.grid_forget()
        self.entry_version.grid_forget()

        self.label_source.grid_forget()
        self.btn_src_curse.grid_forget()
        self.btn_src_other.grid_forget()
        self.entry_download_link.grid_forget()
        self.label_download_link.grid_forget()

        self.label_cf_project_id.grid_forget()
        self.entry_cf_project_id.grid_forget()
        self.label_browser_url.grid_forget()
        self.entry_browser_url.grid_forget()

        self.btn_add.grid_forget()

        self.entry_license.grid_forget()
        self.label_license.grid_forget()

        self.label_project_url.grid_forget()
        self.entry_project_url.grid_forget()

        self.update_idletasks()

    def show(self) -> None:
        """
        Method used to display widgets and child widgets, as well as to configure the "responsiveness" of the widgets.

        :return: None
        """
        x: int = 0
        y: int = 0
        rows: int = 9
        columns: int = 3

        for i in range(rows + 1):
            self.rowconfigure(i, weight=1, pad=self.xpadding)

        for i in range(columns + 1):
            self.columnconfigure(i, weight=1, pad=self.ypadding)

        if self.add_mod_and_version:
            self.label_source.grid(row=x, column=y)
            self.btn_src_curse.grid(row=x, column=y + 1)
            self.btn_src_other.grid(row=x, column=y + 2)

            self.label_name.grid(row=x + 1, column=y)
            self.entry_mod_name.grid(row=x + 1, column=y + 1, columnspan=2)

        self.label_version.grid(row=x + 2, column=y)
        self.entry_version.grid(row=x + 2, column=y + 1, columnspan=2)

        self.label_download_link.grid(row=x + 3, column=y)
        self.entry_download_link.grid(row=x + 3, column=y + 1, columnspan=2)

        if self.int_var_src.get() == 1:  # for curse mods
            if self.add_mod_and_version:
                self.label_cf_project_id.grid(row=x + 4, column=y)
                self.entry_cf_project_id.grid(row=x + 4, column=y + 1, columnspan=2)

        if self.add_mod_and_version:
            self.label_browser_url.grid(row=x + 5, column=y)
            self.entry_browser_url.grid(row=x + 5, column=y + 1, columnspan=2)
            self.label_license.grid(row=x + 6, column=y)
            self.entry_license.grid(row=x + 6, column=y + 1, columnspan=2)
            self.label_project_url.grid(row=x + 7, column=y)
            self.entry_project_url.grid(row=x + 7, column=y + 1, columnspan=2)

        self.btn_add.grid(row=x + 8, column=1)

        self.update_idletasks()

    def populate_data(self, data: Any) -> None:
        """
        Method called by parent class to populate data in this class.

        :param data: the data to pass to this class
        :return: None
        """
        pass
