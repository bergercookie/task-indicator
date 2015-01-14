# encoding=utf-8

import gtk
import json
import os
import re
import shlex
import time

from taskindicator import util


FREQUENCY = 1


def get_database_folder():
    out = util.run_command(["task", "_show"])

    for line in out.split("\n"):
        if line.startswith("data.location="):
            return line.split("=", 1)[1]

    raise RuntimeException("Could not find database location.")


class Task(dict):
    def __repr__(self):
        s = "<Task {0}".format(self["uuid"][:8])
        s += ", status={0}".format(self["status"])
        if "project" in self:
            # FIXME: test with unicode names
            s += ", pro:{0}".format(self["project"])
        if "priority" in self:
            s += ", pri:{0}".format(self["priority"])
        if "start" in self:
            s += ", dur:{0}".format(self.format_current_runtime())
        s += ">"
        return s

    def __getitem__(self, key):
        if key == "tags":
            return self.get("tags", [])
        return super(Task, self).get(key, None)

    def is_active(self):
        if not self.get("start"):
            return False
        return True

    def get_current_runtime(self):
        if not self.get("start"):
            return 0

        start = int(self["start"])
        duration = time.time() - start
        return int(duration)

    def format_current_runtime(self):
        duration = self.get_current_runtime()

        seconds = duration % 60
        minutes = (duration / 60) % 60
        hours = (duration / 3600) % 60

        return "%u:%02u:%02u" % (hours, minutes, seconds)

    def set_note(self, note):
        if not self.get("uuid"):
            raise RuntimeError(
                "Cannot set a note for an unsaved task (no uuid).")

        if not isinstance(note, (str, unicode)):
            raise ValueError("Note must be a text string.")

        if note == self.get_note():
            return

        if isinstance(note, unicode):
            note = note.encode("utf-8")

        folder = os.path.join(
            get_database_folder(),
            "notes")
        if not os.path.exists(folder):
            os.makedirs(folder)
            util.log("Created folder {0}.", folder)

        fn = os.path.join(folder, self["uuid"])

        if note.strip():
            with open(fn, "wb") as f:
                f.write(note)
                util.log("Wrote a note to {0}", fn)
        elif os.path.exists(fn):
            os.unlink(fn)
            util.log("Deleted a note file {0}", fn)

    def get_note(self):
        if not self.get("uuid"):
            return None

        fn = os.path.join(
            get_database_folder(),
            "notes",
            self["uuid"])
        if os.path.exists(fn):
            with open(fn, "rb") as f:
                return f.read().decode("utf-8")
        return u""


class Tasks(object):
    def __init__(self):
        self.tasks = []

        database_folder = get_database_folder()

        db = os.path.join(database_folder, "pending.data")
        self.tasks += self.load_data(db)

        db = os.path.join(database_folder, "completed.data")
        self.tasks += self.load_data(db)

    def load_data(self, database):
        """Reads the database file, parses it and returns a list of Task object
        instances, which contain all parsed data (values are unicode).

        This home-made parser returns raw timestamps, while 'task export'
        returns formatted UTC based dates which are hard to convert to
        timestamps to calculate activity duration, etc.

        TODO: find out a way to convert dates like '20130201T103640Z' to UNIX
        timestamp or at least a datetime.
        """
        _start = time.time()

        if not os.path.exists(database):
            util.log("Database {0} does not exist.", database)
            return {}

        with open(database, "rb") as f:
            raw_data = f.read()

        tasks = []
        for line in raw_data.rstrip().split("\n"):
            if not line.startswith("[") or not line.endswith("]"):
                raise ValueError("Unsupported file format " \
                    "in {0}".format(database))

            task = Task()
            for kw in shlex.split(line[1:-1]):
                if ":" not in kw:
                    util.log("Warning: malformed database token: {0}", kw)
                    continue
                k, v = kw.split(":", 1)
                v = v.replace("\/", "/")  # FIXME: must be a better way
                v = v.decode("utf-8")
                if k == "tags":
                    v = v.split(",")
                task[k] = v

            tasks.append(task)

        tasks = self.merge_exported(tasks)

        util.log("Task database read in {0} seconds.", time.time() - _start)

        return tasks

    def merge_exported(self, tasks):
        """Merges data reported by task.  This is primarily used to get real
        urgency, maybe something else in the future."""
        out = util.run_command(["task", "rc.json.array=1", "export"])

        _tasks = {}
        for em in json.loads(out):
            _tasks[em["uuid"]] = em

        for idx, task in enumerate(tasks):
            if task["uuid"] not in _tasks:
                util.log("Warning: task {0} not exported by TaskWarrior.", task["uuid"])
                continue

            _task = _tasks[task["uuid"]]
            if "urgency" in _task:
                tasks[idx]["urgency"] = float(_task["urgency"])

        return tasks

    def __iter__(self):
        return iter(self.tasks)

    def __getitem__(self, key):
        for task in self.tasks:
            if task["uuid"] == key:
                return task

    def __len__(self):
        return len(self.tasks)


class Database(object):
    def __init__(self):
        self.filename = self.get_filename()
        self.mtime = None
        self._tasks = None

    def modified_since(self, ts):
        return os.stat(self.filename).st_mtime > ts

    def get_filename(self):
        for line in util.run_command(["task", "_show"]).split("\n"):
            if line.startswith("data.location="):
                folder = line.split("=", 1)[1].strip()
                return os.path.join(folder, "pending.data")
        raise RuntimeError("Could not find task database location.")

    def get_tasks(self):
        if self._tasks is None:
            util.log("Reloading tasks.")
            self._tasks = self.load_tasks()
        return self._tasks

    def get_projects(self):
        projects = {}
        for task in self.get_tasks():
            projects[task["project"]] = True
        return projects.keys()

    def refresh(self):
        self._tasks = None
        return self.get_tasks()

    def load_tasks(self):
        return Tasks()

    def get_task_info(self, task_id):
        return Tasks()[task_id]

    def start_task(self, task_id):
        util.log("Starting task {0}.", task_id)
        util.run_command(["task", task_id, "start"])

    def stop_task(self, task_id):
        util.log("Stopping task {0}.", task_id)
        util.run_command(["task", task_id, "stop"])

    def finish_task(self, task_id):
        util.log("Finishing task {0}.", task_id)
        util.run_command(["task", task_id, "stop"])
        util.run_command(["task", task_id, "done"])

    def restart_task(self, task_id):
        util.log("Restarting task {0}.", task_id)
        util.run_command(["task", task_id, "mod", "status:pending"])
        util.run_command(["task", task_id, "start"])

    def update_task(self, task_id, properties):
        command = ["task", task_id, "mod"]

        for k, v in properties.items():
            if k == "uuid":
                continue
            if k == "tags":
                for tag in v:
                    if tag.strip():
                        command.append(tag)
            elif k == "description":
                command.append(v)
            elif k == "note":
                task = Task(uuid=task_id)
                task.set_note(v)
            else:
                command.append("{0}:{1}".format(k, v))

            util.run_command(command)

    def add_task(self, properties):
        command = ["task", "add"]

        for k, v in properties.items():
            if k == "uuid":
                continue
            if k == "tags":
                for tag in v:
                    if tag.strip():
                        command.append(tag)
            elif k == "description":
                command.append(v)
            else:
                command.append("{0}:{1}".format(k, v))

            output = util.run_command(command)

            for _taskno in re.findall("Created task (\d+)", output):
                uuid = util.run_command(["task", _taskno, "uuid"]).strip()
                util.log("New task uuid: {0}", uuid)
                return uuid
