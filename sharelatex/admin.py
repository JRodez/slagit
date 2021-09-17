import codecs
import datetime
import os
import shutil
import zipfile

import pymongo
from bson.json_util import dumps
from bson.objectid import ObjectId


mongo_user = os.environ["MONGO_USER"]
mongo_pass = os.environ["MONGO_PASS"]
mongo_host = os.environ.get("MONGO_HOST", "127.0.0.1")
client = pymongo.MongoClient(f"mongodb://{mongo_user}:{mongo_pass}@{mongo_host}")

DB = client["sharelatex"]



def _writeProjectFiles(
    project,
    destination_path=u"/tmp/",
    user_file_path=u"/var/lib/sharelatex/data/user_files",
):

    projectPath = os.path.join(destination_path, project[u"name"])
    project_id = project[u"_id"]

    def _writeFolders(folders, currentPath):
        for folder in folders:
            newPath = os.path.join(currentPath, folder[u"name"])
            if not os.path.exists(newPath):
                os.makedirs(newPath)
            for doc in folder[u"docs"]:
                doc_db = DB["docs"].find({"_id": doc["_id"]}).limit(1)
                filePath = os.path.join(newPath, doc[u"name"])
                with codecs.open(filePath, "w", "utf-8") as text_file:
                    text_file.write("\n".join(doc_db[0][u"lines"]))
                print(doc[u"name"])
            for file_ref in folder[u"fileRefs"]:
                print(file_ref["name"])
                source = os.path.join(
                    user_file_path, str(project_id) + u"_" + str(file_ref[u"_id"])
                )
                destination = os.path.join(newPath, file_ref[u"name"])
                try:
                    shutil.copyfile(source, destination)
                except IOError:
                    print(
                        "file {file} : {source} not found ".format(
                            file=file_ref[u"name"], source=source
                        )
                    )
                    print(
                        "unable to copy to {destination}".format(
                            destination=destination
                        )
                    )
            _writeFolders(folder[u"folders"], newPath)

    if not os.path.exists(projectPath):
        os.makedirs(projectPath)
    _writeFolders(project[u"rootFolder"], projectPath)


def getZipProject(project_uid, destination_path, user_file_path):
    """Make a zip of a project given a project uid"""
    projectPath = os.path.join(destination_path, project_uid)
    if not os.path.exists(projectPath):
        os.makedirs(projectPath)
    projects = DB["projects"].find({u"_id": ObjectId(project_uid)})
    for project in projects:
        if not os.path.exists(projectPath):
            os.makedirs(projectPath)
        _writeProjectFiles(project, projectPath, user_file_path)

    def zipdir(path, zip_handle):
        for root, dirs, files in os.walk(path):
            for file in files:
                zip_handle.write(os.path.join(root, file))

    zipPath = os.path.join(destination_path, project_uid + u".zip")
    zip_handle = zipfile.ZipFile(zipPath, "w", zipfile.ZIP_DEFLATED)
    zipdir(projectPath, zip_handle)
    zip_handle.close()


def get_inactive_projects(days=365):
    """return a dict containing in keys the ids of the inactive projects since the number
    of day passed in parameter, and in value their lastUpdated date"""

    ids_and_lastUpadted = {}
    projects = DB["projects"]

    date = datetime.datetime.now() - datetime.timedelta(days=days)
    inactive_projects = projects.find({"lastUpdated": {"$lt": date}})

    for inactive_project in inactive_projects:
        ids_and_lastUpadted[str(inactive_project["_id"])] = inactive_project[
            "lastUpdated"
        ]

    return ids_and_lastUpadted


def get_project_collaborators(project_id):
    """return a dict containing in keys the ids of the collaborators for
    the project of project_id id, and in values their mail adress"""
    project = DB["projects"].find({"_id": ObjectId(project_id)})
    result = {}

    for p in project:
        collab_refs = p["collaberator_refs"]
        for ref_id in collab_refs:
            collaborator = DB["users"].find({"_id": ref_id})
            for c in collaborator:
                result[str(ref_id)] = c["email"]

    return result


def changeMailAdress(old_adress, new_adress):
    # new_adress mustn't already be in DB
    if DB.users.find({"email": new_adress}).count() != 0:
        raise NameError("NewAdressAlreadyInDB")
    return DB.users.update_one(
        {"email": old_adress}, {"$set": {"email": new_adress}}
    )


def changeProjectOnwer(project_id, new_onwer_id):
    project = DB["projects"].find({"_id": ObjectId(project_id)}).limit(1)
    if project.count() == 0:
        raise NameError("ProjectIdNotDB")
    users = DB.users.find({"_id": ObjectId(new_onwer_id)})
    if users.count() == 0:
        raise NameError("UserIdNotInDB")
    return DB["projects"].update_one(
        {"_id": ObjectId(project_id)}, {"$set": {"owner_ref": ObjectId(new_onwer_id)}}
    )
