import logging
import os
from pathlib import Path

import getpass

from sharelatex import SyncClient, walk_files, walk_project_data

import click
from git import Repo
from git.config import cp
from zipfile import ZipFile
import keyring

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.DEBUG)

SLATEX_SECTION = "slatex"
SYNC_BRANCH = "__remote__sharelatex__"
PROMPT_BASE_URL = "Base url: "
PROMPT_PROJECT_ID = "Project id: "
PROMPT_USERNAME = "Username: "
PROMPT_PASSWORD = "Password: "
PROMPT_CONFIRM = "Do you want to save your password in your OS keyring system (y/n) ?"


class Config:
    """Handle gitconfig read/write operations in a transparent way."""

    def __init__(self, repo):
        self.repo = repo
        self.keyring = keyring.get_keyring()

    def get_password(self, service, username):
        return self.keyring.get_password(service, username)

    def set_password(self, service, username, password):
        self.keyring.set_password(service, username, password)

    def set_value(self, section, key, value, config_level="repository"):
        """Set a config value in a specific section.

        Note:
            If the section doesn't exist it is created.

        Args:
            section (str): the section name
            key (str): the key to set
            value (str): the value to set
        """
        with self.repo.config_writer(config_level) as c:
            try:
                c.set_value(section, key, value)
            except cp.NoSectionError as e:
                # No section is found, we create a new one
                logging.debug(e)
                c.set_value(section, "init", "")
            except Exception as e:
                raise e
            finally:
                c.release()

    def get_value(self, section, key, default=None, config_level=None):
        """Get a config value in a specific section of the config.

        Note: this returns the associated value if found.
              Otherwise it returns the default value.

        Args:
            section (str): the section name
            key (str): the key to set
            default (str): the defaut value to apply
            config_level (str): the config level to look for
            see:
https://gitpython.readthedocs.io/en/stable/reference.html#git.repo.base.Repo.config_level

        """
        with self.repo.config_reader(config_level) as c:
            try:
                value = c.get_value(section, key)
            except cp.NoSectionError as e:
                logging.debug(e)
                value = default
            except cp.NoOptionError as e:
                logging.debug(e)
                value = default
            except Exception as e:
                raise e
            finally:
                return value


def get_clean_repo(path=None):
    """Create the git.repo object from a directory.

    Note:

        This initialize the git repository and fails if the repo isn't clean.
        This is run prior to many operations to make sure there isn't any
        untracked/uncomitted files in the repo.

    Args:
        path (str): the path of the repository in the local file system.

    Returns:
        a git.Repo data-structure.

    Raises:
        Exception if the repo isn't clean
    """
    repo = Repo.init(path=path)
    # Fail if the repo is clean
    if repo.is_dirty(index=True, working_tree=True, untracked_files=True):
        print(repo.git.status())
        raise Exception("The repo isn't clean.")
    return repo


def refresh_project_information(
    repo, base_url=None, project_id=None, https_cert_check=None
):
    """Get and/or set the project information in/from the git config.

    If the information is set in the config it is retrieved, otherwise it is set.

    Args:
        repo (git.Repo): The repo object to read the config from
        base_url (str): the base_url to consider
        project_id (str): the project_id to consider

    Returns:
        tupe (base_url, project_id) after the refresh occurs.
    """
    config = Config(repo)
    if base_url is None:
        u = config.get_value(SLATEX_SECTION, "baseUrl")
        if u is not None:
            base_url = u
        else:
            base_url = input(PROMPT_BASE_URL)
            config.set_value(SLATEX_SECTION, "baseUrl", base_url)
    else:
        config.set_value(SLATEX_SECTION, "baseUrl", base_url)
    if project_id is None:
        p = config.get_value(SLATEX_SECTION, "projectId")
        if p is not None:
            project_id = p
        else:
            project_id = input(PROMPT_PROJECT_ID)
        config.set_value(SLATEX_SECTION, "projectId", project_id)
    else:
        config.set_value(SLATEX_SECTION, "projectId", project_id)
    if https_cert_check is None:
        c = config.get_value(SLATEX_SECTION, "httpsCertCheck")
        if c is not None:
            https_cert_check = c
        else:
            https_cert_check = True
            config.set_value(SLATEX_SECTION, "httpsCertCheck", https_cert_check)
    else:
        config.set_value(SLATEX_SECTION, "httpsCertCheck", https_cert_check)

    return base_url, project_id, https_cert_check


def refresh_account_information(repo, username=None, password=None, save_password=None):
    """Get and/or set the account information in/from the git config.

    If the information is set in the config it is retrieved, otherwise it is set.
    Note that no further encryption of the password is offered here.

    Args:
        repo (git.Repo): The repo object to read the config from
        username (str): The username to consider
        password (str): The password to consider
        save_password (boolean): True for save user account information (in OS
                                 keyring system) if needed

    Returns:
        tupe (username, password) after the refresh occurs.
    """
    config = Config(repo)
    base_url = config.get_value(SLATEX_SECTION, "baseUrl")

    if username is None:
        u = config.get_value(SLATEX_SECTION, "username")
        if u:
            username = u
        else:
            username = input(PROMPT_USERNAME)
    config.set_value(SLATEX_SECTION, "username", username)

    if password is None:
        p = config.get_password(base_url, username)
        if p:
            password = p
        else:
            password = getpass.getpass(PROMPT_PASSWORD)
            if save_password is None:
                r = input(PROMPT_CONFIRM)
                if r == "Y" or r == "y":
                    save_password = True
    if save_password:
        config.set_password(base_url, username, password)
    return username, password


def update_ref(repo, message="update_ref"):
    """Makes the remote pointer to point on the latest revision we have.

    This is called after a successfull clone, push, new. In short when we
    are sure the remote and the local are in sync.
    """
    git = repo.git

    git.add(".")
    # with this we can have two consecutive commit with the same content
    repo.index.commit(f"{message}")
    sync_branch = repo.create_head(SYNC_BRANCH, force=True)
    sync_branch.commit = "HEAD"


@click.group()
def cli():
    pass


def _pull(repo, client, project_id):
    if repo.is_dirty(index=True, working_tree=True, untracked_files=True):
        print(repo.git.status())
        print("The repository isn't clean")
        return

    # attempt to "merge" the remote and the local working copy

    # TODO(msimonin) get current branch
    # here we assume master
    git = repo.git
    git.checkout(SYNC_BRANCH)

    # delete all files but not .git !!!!
    files = list(Path(repo.working_tree_dir).rglob("*"))
    files.reverse()
    for p in files:
        if not str(p.relative_to(Path(repo.working_tree_dir))).startswith(".git"):
            if p.is_dir():
                p.rmdir()
            else:
                Path.unlink(p)

    # TODO: try to check directly from server what file or directory
    # is changed/delete/modify instead to reload whole project zip
    client.download_project(project_id)
    update_ref(repo, message="pre pull")
    git.checkout("master")
    git.merge(SYNC_BRANCH)


@cli.command(help="Compile the remote version of a project")
@click.argument("project_id", default="")
def compile(project_id):
    repo = Repo()
    base_url, project_id, https_cert_check = refresh_project_information(repo)
    username, password = refresh_account_information(repo)
    client = SyncClient(
        base_url=base_url, username=username, password=password, verify=https_cert_check
    )

    response = client.compile(project_id)
    print(response)


@cli.command(help="Send a invitation to share (edit/view) a project")
@click.argument("email", default="")
@click.option("--project_id", default=None)
@click.option(
    "--can-edit/--read-only",
    default=True,
    help="""Authorize user to edit the project or not""",
)
def share(project_id, email, can_edit):
    repo = Repo()
    base_url, project_id, https_cert_check = refresh_project_information(
        repo, project_id=project_id
    )
    username, password = refresh_account_information(repo)
    client = SyncClient(
        base_url=base_url, username=username, password=password, verify=https_cert_check
    )

    response = client.share(project_id, email, can_edit)
    print(response)


@cli.command(
    help=f"""Pull the files from sharelatex.
    
    In the current repository, it works as follows:
    
    1. Pull in ``{SYNC_BRANCH}`` branch the latest version of the remote project\n
    2. Attempt a merge in the working branch. If the merge can't be done automatically, 
       you will be required to fix the conflixt manually
    """
)
def pull():
    repo = Repo()
    base_url, project_id, https_cert_check = refresh_project_information(repo)
    username, password = refresh_account_information(repo)
    client = SyncClient(
        base_url=base_url, username=username, password=password, verify=https_cert_check
    )
    # Fail if the repo is clean
    _pull(repo, client, project_id)


@cli.command(
    help=f"""
Get (clone) the files from sharelatex projet URL and create a local git depot.

The optionnal target directory will be created if it doesn't exist. The command 
fails if it already exists. Connection informations can be saved in the local git 
config.

It works as follow:

    1. Download and unzip the remote project in the target directory\n
    2. Initialize a fresh git repository\n
    3. Create an extra ``{SYNC_BRANCH}`` to keep track of the remote versions of the project.
       This branch must not be updated manually.
"""
)
@click.argument(
    "projet_url", default=""
)  # , help="The project url (https://sharelatex.irisa.fr/1234567890)")
@click.argument("directory", default="")  # , help="The target directory")
@click.option(
    "--username",
    "-u",
    default=None,
    help="""Username for sharelatex server account, if user is not provided, it will be asked online""",
)
@click.option(
    "--password",
    "-p",
    default=None,
    help="""User password for sharelatex server, if password is not provided, it will be asked online""",
)
@click.option(
    "--save-password/--no-save-password",
    default=None,
    help="""Save user account information (in OS keyring system)""",
)
@click.option(
    "--https-cert-check/--no-https-cert-check",
    default=True,
    help="""force to check https certificate or not""",
)
def clone(projet_url, directory, username, password, save_password, https_cert_check):
    # TODO : robust parse regexp
    slashparts = projet_url.split("/")
    project_id = slashparts[-1]
    base_url = "/".join(slashparts[:-2])
    if base_url == "":
        raise Exception("projet_url is not well formed or missing")
    if directory == "":
        directory = Path(os.getcwd())
        directory = Path(directory, project_id)
    else:
        directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)

    repo = get_clean_repo(path=directory)

    base_url, project_id, https_cert_check = refresh_project_information(
        repo, base_url, project_id, https_cert_check
    )
    username, password = refresh_account_information(
        repo, username, password, save_password
    )

    client = SyncClient(
        base_url=base_url, username=username, password=password, verify=https_cert_check
    )
    client.download_project(project_id, path=directory)
    # TODO(msimonin): add a decent default .gitignore ?
    update_ref(repo, message="clone")


@cli.command(
    help=f"""Synchronise the local copy with the remote version.
    
This works as follow:

1. The remote version is pulled (see the :program:`pull` command)\n
2. After the merge succeed, the merged version is uploaded back to the remote server.\n
   Note that only the files that have changed (modified/added/removed) will be uploaded. 
"""
)
@click.option("--force", is_flag=True, help="Force push")
def push(force):
    def _upload(client, project_data, path):
        # initial factorisation effort
        logging.debug(f"Uploading {path}")
        project_id = project_data["_id"]
        dirname = os.path.dirname(path)
        # TODO: that smells
        dirname = "/" + dirname
        # TODO encapsulate both ?
        folder_id = client.check_or_create_folder(project_data, dirname)
        p = f"{repo.working_dir}/{path}"
        client.upload_file(project_id, folder_id, p)

    def _delete(client, project_data, path):
        # initial factorisation effort
        logging.debug(f"Deleting {path}")
        project_id = project_data["_id"]
        dirname = os.path.dirname(path)
        # TODO: that smells
        dirname = "/" + dirname
        basename = os.path.basename(path)
        entities = walk_project_data(
            project_data,
            lambda x: x["folder_path"] == dirname and x["name"] == basename,
        )
        # there should be one
        entity = next(entities)
        if entity["type"] == "doc":
            client.delete_document(project_id, entity["_id"])
        elif entity["type"] == "file":
            client.delete_file(project_id, entity["_id"])

    repo = get_clean_repo()
    base_url, project_id, https_cert_check = refresh_project_information(repo)
    username, password = refresh_account_information(repo)
    client = SyncClient(
        base_url=base_url, username=username, password=password, verify=https_cert_check
    )
    if not force:
        _pull(repo, client, project_id)

    master_commit = repo.commit("master")
    sync_commit = repo.commit(SYNC_BRANCH)
    diff_index = sync_commit.diff(master_commit)

    project_data = client.get_project_data(project_id)

    logging.debug("Modify files to upload :")
    for d in diff_index.iter_change_type("M"):
        _upload(client, project_data, d.a_path)

    logging.debug("new files to upload :")
    for d in diff_index.iter_change_type("A"):
        _upload(client, project_data, d.a_path)

    logging.debug("delete files :")
    for d in diff_index.iter_change_type("D"):
        _delete(client, project_data, d.a_path)

    logging.debug("rename files :")
    for d in diff_index.iter_change_type("R"):
        # git mv a b
        # for us this corresponds to
        # 1) deleting the old one (a)
        # 2) creating the new one (b)
        _delete(client, project_data, d.a_path)
        _upload(client, project_data, d.b_path)
    logging.debug("Path type changes :")
    for d in diff_index.iter_change_type("T"):
        # This one is maybe
        # 1) deleting the old one (a)
        # 2) creating the new one (b)
        _delete(client, project_data, d.a_path)
        _upload(client, project_data, d.b_path)

    update_ref(repo, message="push")


@cli.command(
    help="""
Upload the current directory as a new sharelatex project.

This litteraly creates a new remote project in sync with the local version.
"""
)
@click.argument("projectname")
@click.argument("base_url")
@click.option(
    "--username",
    "-u",
    default=None,
    help="""username for sharelatex server account, if user is not provided, it will be asked online""",
)
@click.option(
    "--password",
    "-p",
    default=None,
    help="""user password for sharelatex server, if password is not provided, it will be asked online""",
)
@click.option(
    "--save-password/--no-save-password",
    default=None,
    help="""Save user account information (in OS keyring system)""",
)
@click.option(
    "--https-cert-check/--no-https-cert-check",
    default=True,
    help="""force to check https certificate or not""",
)
def new(projectname, base_url, username, password, save_password, https_cert_check):
    repo = get_clean_repo()
    username, password = refresh_account_information(
        repo, username, password, save_password
    )

    client = SyncClient(
        base_url=base_url, username=username, password=password, verify=https_cert_check
    )
    iter_file = repo.tree().traverse()
    archive_name = "%s.zip" % projectname
    archive_path = Path(archive_name)
    with ZipFile(str(archive_path), "w") as z:
        for f in iter_file:
            logging.debug(f"Adding {f.path} to the archive")
            z.write(f.path)

    response = client.upload(archive_name)
    print("Successfully uploaded %s [%s]" % (projectname, response["project_id"]))
    archive_path.unlink()

    refresh_project_information(
        repo, base_url, response["project_id"], https_cert_check
    )
    update_ref(repo, message="upload")
