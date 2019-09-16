from contextlib import contextmanager
from git import Repo
import os
from sharelatex import SyncClient, walk_project_data
from subprocess import check_call
import tempfile
import unittest


BASE_URL = os.environ.get("CI_BASE_URL")
USERNAME = os.environ.get("CI_USERNAME")
PASSWORD = os.environ.get("CI_PASSWORD")


def log(f):
    def wrapped(*args, **kwargs):
        print("-" * 60)
        print("{:^60}".format(f.__name__.upper()))
        print("-" * 60)
        return f(*args, **kwargs)

    return wrapped


class Project:
    def __init__(self, client, project_id, fs_path, repo=None):
        self.client = client
        self.project_id = project_id
        self.fs_path = fs_path
        self.repo = repo
        self.url = f"{BASE_URL}/project/{project_id}"

    def get_doc_by_path(self, path):
        """Doc only."""

        def predicate(entity):
            return entity["folder_path"] == os.path.dirname(path) and entity[
                "name"
            ] == os.path.basename(path)

        project_data = self.client.get_project_data(self.project_id)
        files = walk_project_data(project_data, predicate=predicate)
        myfile = next(files)
        content = self.client.get_doc(self.project_id, myfile["_id"])
        return content

    def delete_file_by_path(self, path):
        """File only."""

        def predicate(entity):
            return entity["folder_path"] == os.path.dirname(path) and entity[
                "name"
            ] == os.path.basename(path)

        project_data = self.client.get_project_data(self.project_id)
        files = walk_project_data(project_data, predicate=predicate)
        myfile = next(files)
        self.client.delete_file(self.project_id, myfile["_id"])


@contextmanager
def project(project_name):
    """A convenient contextmanager to create a temporary project on sharelatex."""
    client = SyncClient(base_url=BASE_URL, username=USERNAME, password=PASSWORD)
    with tempfile.TemporaryDirectory() as temp_path:
        os.chdir(temp_path)
        r = client.new(project_name)
        try:
            project_id = r["project_id"]
            fs_path = os.path.join(temp_path, project_id)
            project = Project(client, project_id, fs_path)

            # let's clone it
            check_call(
                f"git slatex clone {project.url} --username={USERNAME} --password={PASSWORD} --save-password",
                shell=True,
            )
            os.chdir(project.fs_path)
            check_call("git config --local user.email 'test@test.com'", shell=True)
            check_call("git config --local user.name 'me'", shell=True)

            project.repo = Repo()
            yield project
        except Exception as e:
            raise e
        finally:
            client.delete(project_id, forever=True)


def new_project(f):
    """A convenient decorator to launch a function in the context of a new project."""

    def wrapped(*args, **kwargs):
        with project(f.__name__) as p:
            return f(*args, p, **kwargs)

    return wrapped


class TestCli(unittest.TestCase):
    @new_project
    def test_clone(self, project):
        pass

    @new_project
    def test_clone_and_pull(self, project):
        check_call("git slatex pull", shell=True)

    @new_project
    def test_clone_and_push(self, project):
        check_call("git slatex push", shell=True)

    @new_project
    def test_clone_and_push_local_modification(self, project):
        """Local modification on main.tex"""
        check_call("echo test > main.tex", shell=True)
        project.repo.git.add(".")
        project.repo.index.commit("test")

        check_call("git slatex push", shell=True)
        remote_content = project.get_doc_by_path("/main.tex")

        # for some reason there's a trailing \n...
        self.assertEqual("test\n", remote_content)

    @new_project
    def test_clone_and_push_local_addition(self, project):
        """Addition of a file"""
        check_call("echo test > main2.tex", shell=True)
        project.repo.git.add(".")
        project.repo.index.commit("test")
        check_call("git slatex push", shell=True)
        remote_content = project.get_doc_by_path("/main2.tex")

        # for some reason there's a trailing \n...
        self.assertEqual("test\n", remote_content)

    @new_project
    def test_clone_and_push_local_deletion(self, project):
        """Addition of a file"""
        check_call("rm main.tex", shell=True)
        project.repo.git.add(".")
        project.repo.index.commit("test")
        check_call("git slatex push", shell=True)
        with self.assertRaises(StopIteration) as _:
            project.get_doc_by_path("/main.tex")


    @new_project
    def test_clone_and_pull_remote_deletion(self, project):
        """Deletion of universe.png"""
        project.delete_file_by_path("/universe.jpg")
        check_call("git slatex pull", shell=True)
        # TODO: we could check the diff
        self.assertFalse(os.path.exists("universe.jpg"))

    