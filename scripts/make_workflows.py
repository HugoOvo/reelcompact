#!/usr/bin/env python3
"""Install Finder Quick Actions for the two Antigravity compression modes."""

from __future__ import annotations

import plistlib
import shutil
import uuid
from pathlib import Path

HOME = Path.home()
SERVICES = HOME / "Library/Services"
APP = HOME / "Applications/ReelCompact.app"
MODES = (
    ("h264", "压缩到20MB（H.264 兼容）", "dev.hugo.antigravity20mb.h264"),
    ("h265", "压缩到20MB（H.265 高画质）", "dev.hugo.antigravity20mb.h265"),
)


def action_document(codec: str) -> dict:
    command = f'''if [ "$#" -eq 0 ]; then
  exit 0
fi
app="/Applications/ReelCompact.app"
if [ ! -d "$app" ]; then
  app="$HOME/Applications/ReelCompact.app"
fi
if [ ! -d "$app" ]; then
  /usr/bin/osascript -e 'display alert "找不到轻帧 ReelCompact" message "请先把 App 拖到“应用程序”文件夹，再重新启用快速操作。" as critical'
  exit 1
fi
/usr/bin/open -n -a "$app" --args --codec {codec} -- "$@"
'''
    parameter_properties = {
        "CheckedForUserDefaultShell": {},
        "COMMAND_STRING": {},
        "inputMethod": {},
        "shell": {},
        "source": {},
    }
    return {
        "actions": [{
            "action": {
                "ActionBundlePath": "/System/Library/Automator/Run Shell Script.action",
                "ActionName": "Run Shell Script",
                "ActionParameters": {
                    "CheckedForUserDefaultShell": True,
                    "COMMAND_STRING": command,
                    "inputMethod": 1,
                    "shell": "/bin/zsh",
                    "source": "",
                },
                "AMAccepts": {"Container": "List", "Optional": True, "Types": ["com.apple.cocoa.path"]},
                "AMActionVersion": "2.0.3",
                "AMApplication": ["Automator"],
                "AMParameterProperties": parameter_properties,
                "AMProvides": {"Container": "List", "Types": ["com.apple.cocoa.string"]},
                "BundleIdentifier": "com.apple.RunShellScript",
                "CanShowSelectedItemsWhenRun": False,
                "CanShowWhenRun": True,
                "Category": ["AMCategoryUtilities"],
                "CFBundleVersion": "2.0.3",
                "Class Name": "RunShellScriptAction",
                "InputUUID": str(uuid.uuid4()).upper(),
                "Keywords": ["Shell", "Script"],
                "location": "309.000000:305.000000",
                "nibPath": "/System/Library/Automator/Run Shell Script.action/Contents/Resources/Base.lproj/main.nib",
                "OutputUUID": str(uuid.uuid4()).upper(),
                "UnlocalizedApplications": ["Automator"],
                "UUID": str(uuid.uuid4()).upper(),
            },
            "isViewVisible": True,
        }],
        "AMApplicationBuild": "521",
        "AMApplicationVersion": "2.10",
        "AMDocumentVersion": "2",
        "connectors": {},
        "workflowMetaData": {
            "applicationBundleIDsByPath": {},
            "applicationPaths": [],
            "inputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "outputTypeIdentifier": "com.apple.Automator.nothing",
            "presentationMode": 15,
            "processesInput": False,
            "serviceApplicationBundleID": "com.apple.finder",
            "serviceApplicationPath": "/System/Library/CoreServices/Finder.app",
            "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
            "serviceProcessesInput": False,
            "systemImageName": "NSActionTemplate",
            "useAutomaticInputType": False,
            "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
        },
    }


def service_info(name: str, bundle_id: str) -> dict:
    return {
        "CFBundleDevelopmentRegion": "zh_CN",
        "CFBundleExecutable": "",
        "CFBundleIdentifier": bundle_id,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": name,
        "CFBundlePackageType": "BNDL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "NSServices": [{
            "NSBackgroundColorName": "background",
            "NSIconName": "NSActionTemplate",
            "NSMenuItem": {"default": name},
            "NSMessage": "runWorkflowAsService",
            "NSRequiredContext": {"NSApplicationIdentifier": "com.apple.finder"},
            "NSSendFileTypes": ["public.movie"],
        }],
    }


def main() -> None:
    SERVICES.mkdir(parents=True, exist_ok=True)
    for codec, name, bundle_id in MODES:
        workflow = SERVICES / f"{name}.workflow"
        if workflow.exists():
            shutil.rmtree(workflow)
        contents = workflow / "Contents"
        contents.mkdir(parents=True)
        document = action_document(codec)
        with (contents / "document.wflow").open("wb") as handle:
            plistlib.dump(document, handle, sort_keys=False)
        with (contents / "Info.plist").open("wb") as handle:
            plistlib.dump(service_info(name, bundle_id), handle, sort_keys=False)
        print(workflow)


if __name__ == "__main__":
    main()
