from contextlib import contextmanager
from git import Repo
import logging
import os
from subprocess import check_call, check_output
import tempfile
import unittest
import shlex
from pathlib import Path

from sharelatex import SyncClient, walk_project_data, get_authenticator_class

from ddt import ddt, data, unpack


logging.basicConfig(level=logging.DEBUG)


BASE_URL = os.environ.get("CI_BASE_URL")
USERNAMES = os.environ.get("CI_USERNAMES")
PASSWORDS = os.environ.get("CI_PASSWORDS")
AUTH_TYPE = os.environ.get("CI_AUTH_TYPE")

# Operate with a list of users
# This workarounds the rate limitation on the API if enough usernames and passwords are given
# Each test will pick the next (username, password) in the queue and put it back at the end
# An alternative would be to define a smoke user in the settings
# settings.smokeTest = True, settings.smokeTest.UserId
import queue

CREDS = queue.Queue()
for username, password in zip(USERNAMES.split(","), PASSWORDS.split(",")):
    CREDS.put((username, password))


def log(f):
    def wrapped(*args, **kwargs):
        print("-" * 60)
        print("{:^60}".format(f.__name__.upper()))
        print("-" * 60)
        return f(*args, **kwargs)

    return wrapped


class Project:
    def __init__(self, client, project_id, fs_path, username, password, repo=None):
        self.client = client
        self.project_id = project_id
        self.fs_path = fs_path
        self.repo = repo
        self.url = f"{BASE_URL}/project/{project_id}"
        # keep track of who created the project
        self.username = username
        self.password = password

    def get_doc_by_path(self, path):
        """Doc only."""
        path = Path(path)

        def predicate(entity):
            return (
                Path(entity["folder_path"]) == path.parent
                and entity["name"] == path.name
            )

        project_data = self.client.get_project_data(self.project_id)
        files = walk_project_data(project_data, predicate=predicate)
        myfile = next(files)
        content = self.client.get_document(self.project_id, myfile["_id"])
        return content

    def delete_object_by_path(self, path):
        """File and  documents only"""
        path = Path(path)

        def predicate(entity):
            return (
                Path(entity["folder_path"]) == path.parent
                and entity["name"] == path.name
            )

        project_data = self.client.get_project_data(self.project_id)
        objects = walk_project_data(project_data, predicate=predicate)
        object = next(objects)
        if object["type"] == "doc":
            self.client.delete_document(self.project_id, object["_id"])
        if object["type"] == "file":
            self.client.delete_file(self.project_id, object["_id"])

    def delete_folder_by_path(self, path):
        path = Path(path)

        def predicate(entity):
            return Path(entity["folder_path"]) == path and entity["name"] == "."

        project_data = self.client.get_project_data(self.project_id)
        objects = walk_project_data(project_data, predicate=predicate)
        object = next(objects)
        self.client.delete_folder(self.project_id, object["folder_id"])


@contextmanager
def project(project_name, branch=None):
    """A convenient contextmanager to create a temporary project on sharelatex."""

    # First we create a client.
    # For testing purpose we disable SSL verification everywhere
    username, password = CREDS.get()
    authenticator = get_authenticator_class(AUTH_TYPE)()
    client = SyncClient(
        base_url=BASE_URL,
        username=username,
        password=password,
        authenticator=authenticator,
        verify=False,
    )
    with tempfile.TemporaryDirectory() as temp_path:
        old_dir = Path.cwd()
        os.chdir(temp_path)
        r = client.new(project_name)
        try:
            project_id = r["project_id"]
            fs_path = os.path.join(temp_path, project_id)
            project = Project(client, project_id, fs_path, username, password)

            # let's clone it
            args = f"--auth_type={AUTH_TYPE} --username={username} --password={shlex.quote(password)} --save-password --no-https-cert-check"
            check_call(f"git slatex clone {project.url} {args}", shell=True)
            os.chdir(project.fs_path)
            check_call("git config --local user.email 'test@test.com'", shell=True)
            check_call("git config --local user.name 'me'", shell=True)
            if branch is not None:
                # use branch instead of the original one
                check_call(f"git branch -m {branch}", shell=True)

            project.repo = Repo()
            yield project
        except Exception as e:
            raise e
        finally:
            # going back to the original directory prevent us to be
            # in a deleted directory in the future
            os.chdir(old_dir)
            CREDS.put((username, password))
            client.delete(project_id, forever=True)


def new_project(branch=None):
    def _new_project(f):
        """A convenient decorator to launch a function in the
        context of a new project."""

        def wrapped(*args, **kwargs):
            with project(f.__name__, branch=branch) as p:
                kwargs.update(project=p)
                return f(*args, **kwargs)

        return wrapped

    return _new_project


@ddt
class TestCli(unittest.TestCase):
    @new_project()
    def test_clone(self, project=None):
        pass

    @new_project()
    def test_clone_and_pull(self, project=None):
        check_call("git slatex pull -vvv", shell=True)

    @data("--force", "")
    @new_project()
    def test_clone_and_push(self, force, project=None):
        check_call(f"git slatex push {force} -vvv", shell=True)

    @data("test_branch", None)
    def test_clone_and_push_local_modification(self, branch):
        @new_project(branch=branch)
        def _test_clone_and_push_local_modification(project=None):
            """Local modification on main.tex"""
            check_call("echo test > main.tex", shell=True)
            project.repo.git.add(".")
            project.repo.index.commit("test")

            check_call("git slatex push -vvv", shell=True)
            remote_content = project.get_doc_by_path("./main.tex")

            # for some reason there's a trailing \n...
            self.assertEqual("test\n", remote_content)

        # run it
        _test_clone_and_push_local_modification()

    @data(
        ["--force", None], ["--force", "test_branch"], ["", None], ["", "test_branch"]
    )
    @unpack
    def test_clone_and_push_local_addition(self, force, branch):
        @new_project(branch=branch)
        def _test_clone_and_push_local_addition(project=None):
            """Addition of a local file"""
            check_call("echo test > main2.tex", shell=True)
            project.repo.git.add(".")
            project.repo.index.commit("test")
            check_call(f"git slatex push {force} -vvv", shell=True)
            remote_content = project.get_doc_by_path("./main2.tex")

            # for some reason there's a trailing \n...
            self.assertEqual("test\n", remote_content)

        _test_clone_and_push_local_addition()

    @data("test_branch", None)
    def test_clone_and_pull_remote_addition(self, branch):
        @new_project(branch=branch)
        def _test_clone_and_pull_remote_addition(project=None):
            """Addition of a remote document and a remote file"""
            check_call("mkdir -p test", shell=True)
            check_call("echo test > test/test.tex", shell=True)

            check_call("mkdir -p test_bin", shell=True)
            check_call("cp ./universe.jpg test_bin/test.jpg", shell=True)

            # create the document and the file on the remote copy
            client = project.client
            project_id = project.project_id
            project_data = client.get_project_data(project_id)
            folder_id = client.check_or_create_folder(project_data, "./test")
            client.upload_file(project_id, folder_id, "test/test.tex")
            folder_bin_id = client.check_or_create_folder(project_data, "./test_bin")
            client.upload_file(project_id, folder_bin_id, "test_bin/test.jpg")

            # remove local document and file
            check_call("rm -rf test", shell=True)
            self.assertFalse(os.path.exists("test/test.tex"))
            check_call("rm -rf test_bin", shell=True)
            self.assertFalse(os.path.exists("test_bin/test.jpg"))

            # pull
            check_call("git slatex pull -vvv", shell=True)

            # check the document
            self.assertTrue(os.path.exists("test/test.tex"))
            # check content (there's an extra \n...)
            self.assertEqual("test\n", open("test/test.tex", "r").read())

            # check the file
            self.assertTrue(os.path.exists("test_bin/test.jpg"))
            # TODO: check content of file
            from filecmp import cmp

            self.assertTrue(cmp("test_bin/test.jpg", "universe.jpg", shallow=False))

        _test_clone_and_pull_remote_addition()

    @data(
        ["--force", None], ["--force", "test_branch"], ["", None], ["", "test_branch"]
    )
    @unpack
    def test_clone_and_push_local_deletion(self, force, branch):
        @new_project(branch=branch)
        def _test_clone_and_push_local_deletion(project=None):
            """Deletion of a local file"""
            check_call("rm main.tex", shell=True)
            project.repo.git.add(".")
            project.repo.index.commit("test")
            check_call(f"git slatex push {force} -vvv", shell=True)
            with self.assertRaises(StopIteration) as _:
                project.get_doc_by_path("./main.tex")

        _test_clone_and_push_local_deletion()

    @data(
        ["--force", None], ["--force", "test_branch"], ["", None], ["", "test_branch"]
    )
    @unpack
    def test_clone_and_pull_remote_deletion(self, force, branch):
        @new_project(branch=branch)
        def _test_clone_and_pull_remote_deletion(project=None, path="."):
            """Deletion of remote path"""
            project.delete_object_by_path(path)
            check_call("git slatex pull -vvv", shell=True)
            # TODO: we could check the diff
            self.assertFalse(os.path.exists(path))

        _test_clone_and_pull_remote_deletion(path="./universe.jpg")
        _test_clone_and_pull_remote_deletion(path="./references.bib")

    @data(
        [
            "--force",
            None,
        ]  # , ["--force", "test_branch"], ["", None], ["", "test_branch"]
    )
    @unpack
    def test_clone_and_pull_remote_folder_deletion(self, force, branch):
        @new_project(branch=branch)
        def _test_clone_and_pull_remote_folder_deletion(project=None, path="."):
            path = Path(path)
            file_test_path = path.joinpath("test.tex")
            """Addition of a remote file."""
            check_call(f"mkdir -p {path}", shell=True)
            check_call(f"echo test > {file_test_path}", shell=True)
            # create the file on the remote copy
            client = project.client
            project_id = project.project_id
            project_data = client.get_project_data(project_id)
            folder_id = client.check_or_create_folder(project_data, path)
            client.upload_file(project_id, folder_id, file_test_path)
            check_call(f"rm -rf {path}", shell=True)
            # update local project copy
            check_call("git slatex pull -vvv", shell=True)
            self.assertTrue(path.exists())
            self.assertTrue(file_test_path.exists())
            """Deletion of remote path"""
            project.delete_folder_by_path(path)
            check_call("git slatex pull -vvv", shell=True)
            # TODO: we could check the diff
            self.assertFalse(os.path.exists(path))

        _test_clone_and_pull_remote_folder_deletion(path="./test_dir")


    @new_project(branch="main")
    def test_clone_and_pull_addgitignore(self, project=None):
        path = Path(project.fs_path)

        gitignore = path / ".gitignore"
        pdf = path / "main.pdf"
        # ignoring pdf files
        check_call(f"echo '*.pdf'> {gitignore}", shell=True)
        # create a dummy pdf file
        check_call(f"echo 'this is an ignored pdf'> {pdf}", shell=True)

        # committing (only .gitingore)
        project.repo.git.add(".gitignore")
        project.repo.index.commit("test")

        # we're clean, pulling
        check_call("git slatex pull -vvv", shell=True)
        self.assertTrue(gitignore.exists(), "gitignore was committed and mustn't be deleted")
        self.assertTrue(pdf.exists(), "gitignored file mustn't be deleted")


    def test_clone_malformed_project_URL(self):
        """try clone with malformed project URL"""
        with self.assertRaises(Exception) as _:
            check_call("git slatex clone not_a_PROJET_URL -vvv", shell=True)

    @new_project()
    def test_new(self, project):
        username = project.username
        password = project.password
        check_call(
            f"git slatex new test_new {BASE_URL} --username {username} --password {shlex.quote(password)} --auth_type {AUTH_TYPE}",
            shell=True,
        )


class TestLib(unittest.TestCase):
    @new_project()
    def test_copy(self, project=None):
        client = project.client
        response = client.clone(project.project_id, "cloned_project")
        client.delete(response["project_id"], forever=True)

    @new_project()
    def test_update_project_settings(self, project=None):
        client = project.client
        response = client.update_project_settings(project.project_id, name="RENAMED")
        project_data = client.get_project_data(project.project_id)
        self.assertEqual("RENAMED", project_data["name"])


if __name__ == "__main__":
    unittest.main(verbosity=3)
