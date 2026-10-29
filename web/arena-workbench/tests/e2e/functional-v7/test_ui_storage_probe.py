# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Sandbox-only admission/staging negatives; never starts a browser."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ui_storage_probe as probe


def synthetic_native_cases():
    """Recorded-shape synthetic checker fixtures, NOT a browser execution.

    One data-only trace per case; references, raw records and prefix cuts expand
    here. Source shape was captured by the native runner, but these unit values
    are deliberately reserialized and labelled synthetic. No IDB is invoked.
    """
    import copy
    import json
    data = json.loads(r'''{
"two-pages-concurrent-pins":{"before":[[0,[[],[]]],[0,[[],[]]]],"after":[[2,[[0,1],[]]],[2,[[0,1],[]]]],"schedule":"two native command transactions queued behind active readwrite barrier; writes serialize, not simultaneous execution","queued":[{"cut":[0,14,["persistent",[[],[]],""]]},{"cut":[1,11,["persistent",[[],[]],""]]}],"outcomes":["committed","committed"],"audits":[{"events":[{"type":"snapshot","mode":"initializing"},{"type":"transaction-created","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"get-success","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"put-success","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"transaction-complete","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"snapshot","mode":"persistent"},{"type":"transaction-created","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"get-success","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"transaction-complete","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"connection-close","connection":2,"version":1},{"type":"transaction-created","tx":3,"connection":3,"label":"barrier","mode":"readwrite"},{"type":"barrier-active"},{"type":"command-start","index":0},{"type":"transaction-created","tx":4,"connection":1,"label":"command","mode":"readwrite"},{"type":"barrier-release","count":262},{"type":"transaction-complete","tx":3,"connection":3,"label":"barrier","mode":"readwrite"},{"type":"connection-close","connection":3,"version":1},{"type":"barrier-complete","count":263},{"type":"get-success","tx":4,"connection":1,"label":"command","mode":"readwrite"},{"type":"put-success","tx":4,"connection":1,"label":"command","mode":"readwrite"},{"type":"transaction-complete","tx":4,"connection":1,"label":"command","mode":"readwrite"},{"type":"snapshot","mode":"persistent"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"production"},{"type":"command-outcome","index":0,"outcome":"committed"},{"type":"transaction-created","tx":5,"connection":1,"label":"command","mode":"readonly"},{"type":"get-success","tx":5,"connection":1,"label":"command","mode":"readonly"},{"type":"transaction-complete","tx":5,"connection":1,"label":"command","mode":"readonly"},{"type":"snapshot","mode":"persistent"},{"type":"transaction-created","tx":6,"connection":1,"label":"refresh","mode":"readonly"},{"type":"get-success","tx":6,"connection":1,"label":"refresh","mode":"readonly"},{"type":"transaction-complete","tx":6,"connection":1,"label":"refresh","mode":"readonly"},{"type":"transaction-created","tx":7,"connection":4,"label":"refresh","mode":"readonly"},{"type":"get-success","tx":7,"connection":4,"label":"refresh","mode":"readonly"},{"type":"transaction-complete","tx":7,"connection":4,"label":"refresh","mode":"readonly"},{"type":"connection-close","connection":4,"version":1}],"snapshot":["persistent",[[0,1],[]],""]},{"events":[{"type":"snapshot","mode":"initializing"},{"type":"transaction-created","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"get-success","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"transaction-complete","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"snapshot","mode":"persistent"},{"type":"transaction-created","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"get-success","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"transaction-complete","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"connection-close","connection":2,"version":1},{"type":"command-start","index":1},{"type":"transaction-created","tx":3,"connection":1,"label":"command","mode":"readwrite"},{"type":"get-success","tx":3,"connection":1,"label":"command","mode":"readwrite"},{"type":"transaction-created","tx":4,"connection":1,"label":"command","mode":"readonly"},{"type":"put-success","tx":3,"connection":1,"label":"command","mode":"readwrite"},{"type":"transaction-complete","tx":3,"connection":1,"label":"command","mode":"readwrite"},{"type":"snapshot","mode":"persistent"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"production"},{"type":"command-outcome","index":1,"outcome":"committed"},{"type":"get-success","tx":4,"connection":1,"label":"command","mode":"readonly"},{"type":"transaction-complete","tx":4,"connection":1,"label":"command","mode":"readonly"},{"type":"transaction-created","tx":5,"connection":1,"label":"refresh","mode":"readonly"},{"type":"get-success","tx":5,"connection":1,"label":"refresh","mode":"readonly"},{"type":"transaction-complete","tx":5,"connection":1,"label":"refresh","mode":"readonly"},{"type":"transaction-created","tx":6,"connection":3,"label":"refresh","mode":"readonly"},{"type":"get-success","tx":6,"connection":3,"label":"refresh","mode":"readonly"},{"type":"transaction-complete","tx":6,"connection":3,"label":"refresh","mode":"readonly"},{"type":"connection-close","connection":3,"version":1}],"snapshot":["persistent",[[0,1],[]],""]}],"closed":[[35,[{"type":"connection-close","connection":1,"version":1},{"type":"fixture-closed"}],["persistent",[[0,1],[]],""]],[27,[{"type":"connection-close","connection":1,"version":1},{"type":"fixture-closed"}],["persistent",[[0,1],[]],""]]]},
"competing-pins-at-capacity":{"before":[[0,[[0,1,2,3,4,5,6],[]]],[0,[[0,1,2,3,4,5,6],[]]]],"after":[[1,[[0,1,2,3,4,5,6,7],[]]],[1,[[0,1,2,3,4,5,6,7],[]]]],"schedule":"two native command transactions queued behind active readwrite barrier; writes serialize, not simultaneous execution","queued":[{"cut":[0,17,["persistent",[[0,1,2,3,4,5,6],[]],""]]},{"cut":[1,11,["persistent",[[0,1,2,3,4,5,6],[]],""]]}],"outcomes":["committed","limit"],"audits":[{"events":[{"type":"transaction-created","tx":1,"connection":1,"label":"seed","mode":"readwrite"},{"type":"put-success","tx":1,"connection":1,"label":"seed","mode":"readwrite"},{"type":"transaction-complete","tx":1,"connection":1,"label":"seed","mode":"readwrite"},{"type":"connection-close","connection":1,"version":1},{"type":"snapshot","mode":"initializing"},{"type":"transaction-created","tx":2,"connection":2,"label":"initialize","mode":"readwrite"},{"type":"get-success","tx":2,"connection":2,"label":"initialize","mode":"readwrite"},{"type":"transaction-complete","tx":2,"connection":2,"label":"initialize","mode":"readwrite"},{"type":"snapshot","mode":"persistent"},{"type":"transaction-created","tx":3,"connection":3,"label":"initialize","mode":"readonly"},{"type":"get-success","tx":3,"connection":3,"label":"initialize","mode":"readonly"},{"type":"transaction-complete","tx":3,"connection":3,"label":"initialize","mode":"readonly"},{"type":"connection-close","connection":3,"version":1},{"type":"transaction-created","tx":4,"connection":4,"label":"barrier","mode":"readwrite"},{"type":"barrier-active"},{"type":"command-start","index":7},{"type":"transaction-created","tx":5,"connection":2,"label":"command","mode":"readwrite"},{"type":"barrier-release","count":194},{"type":"transaction-complete","tx":4,"connection":4,"label":"barrier","mode":"readwrite"},{"type":"connection-close","connection":4,"version":1},{"type":"barrier-complete","count":195},{"type":"get-success","tx":5,"connection":2,"label":"command","mode":"readwrite"},{"type":"put-success","tx":5,"connection":2,"label":"command","mode":"readwrite"},{"type":"transaction-complete","tx":5,"connection":2,"label":"command","mode":"readwrite"},{"type":"snapshot","mode":"persistent"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"production"},{"type":"command-outcome","index":7,"outcome":"committed"},{"type":"transaction-created","tx":6,"connection":2,"label":"refresh","mode":"readonly"},{"type":"get-success","tx":6,"connection":2,"label":"refresh","mode":"readonly"},{"type":"transaction-complete","tx":6,"connection":2,"label":"refresh","mode":"readonly"},{"type":"transaction-created","tx":7,"connection":5,"label":"refresh","mode":"readonly"},{"type":"get-success","tx":7,"connection":5,"label":"refresh","mode":"readonly"},{"type":"transaction-complete","tx":7,"connection":5,"label":"refresh","mode":"readonly"},{"type":"connection-close","connection":5,"version":1}],"snapshot":["persistent",[[0,1,2,3,4,5,6,7],[]],""]},{"events":[{"type":"snapshot","mode":"initializing"},{"type":"transaction-created","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"get-success","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"transaction-complete","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"snapshot","mode":"persistent"},{"type":"transaction-created","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"get-success","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"transaction-complete","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"connection-close","connection":2,"version":1},{"type":"command-start","index":8},{"type":"transaction-created","tx":3,"connection":1,"label":"command","mode":"readwrite"},{"type":"get-success","tx":3,"connection":1,"label":"command","mode":"readwrite"},{"type":"transaction-created","tx":4,"connection":1,"label":"command","mode":"readonly"},{"type":"transaction-complete","tx":3,"connection":1,"label":"command","mode":"readwrite"},{"type":"snapshot","mode":"persistent"},{"type":"command-outcome","index":8,"outcome":"limit"},{"type":"get-success","tx":4,"connection":1,"label":"command","mode":"readonly"},{"type":"transaction-complete","tx":4,"connection":1,"label":"command","mode":"readonly"},{"type":"transaction-created","tx":5,"connection":1,"label":"refresh","mode":"readonly"},{"type":"get-success","tx":5,"connection":1,"label":"refresh","mode":"readonly"},{"type":"transaction-complete","tx":5,"connection":1,"label":"refresh","mode":"readonly"},{"type":"transaction-created","tx":6,"connection":3,"label":"refresh","mode":"readonly"},{"type":"get-success","tx":6,"connection":3,"label":"refresh","mode":"readonly"},{"type":"transaction-complete","tx":6,"connection":3,"label":"refresh","mode":"readonly"},{"type":"connection-close","connection":3,"version":1}],"snapshot":["persistent",[[0,1,2,3,4,5,6,7],[]],""]}],"closed":[[34,[{"type":"connection-close","connection":2,"version":1},{"type":"fixture-closed"}],["persistent",[[0,1,2,3,4,5,6,7],[]],""]],[25,[{"type":"connection-close","connection":1,"version":1},{"type":"fixture-closed"}],["persistent",[[0,1,2,3,4,5,6,7],[]],""]]]},
"legacy-exact-unchanged":{"before":[],"after":[[0,[[0,1],[2]]]],"legacyBefore":"  {\"version\":1,\"pins\":[{\"id\":\"editor-revision:11111111111111111111111111111111\",\"kind\":\"editor_revision\",\"revision_id\":\"11111111111111111111111111111111\",\"source_hash\":\"1111111111111111111111111111111111111111111111111111111111111111\",\"canonical_hash\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"},{\"id\":\"editor-revision:22222222222222222222222222222222\",\"kind\":\"editor_revision\",\"revision_id\":\"22222222222222222222222222222222\",\"source_hash\":\"2222222222222222222222222222222222222222222222222222222222222222\",\"canonical_hash\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"}],\"recents\":[{\"id\":\"editor-revision:33333333333333333333333333333333\",\"kind\":\"editor_revision\",\"revision_id\":\"33333333333333333333333333333333\",\"source_hash\":\"3333333333333333333333333333333333333333333333333333333333333333\",\"canonical_hash\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"}]}\n","preMount":{"cut":[0,0,null]},"legacyAfter":"  {\"version\":1,\"pins\":[{\"id\":\"editor-revision:11111111111111111111111111111111\",\"kind\":\"editor_revision\",\"revision_id\":\"11111111111111111111111111111111\",\"source_hash\":\"1111111111111111111111111111111111111111111111111111111111111111\",\"canonical_hash\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"},{\"id\":\"editor-revision:22222222222222222222222222222222\",\"kind\":\"editor_revision\",\"revision_id\":\"22222222222222222222222222222222\",\"source_hash\":\"2222222222222222222222222222222222222222222222222222222222222222\",\"canonical_hash\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"}],\"recents\":[{\"id\":\"editor-revision:33333333333333333333333333333333\",\"kind\":\"editor_revision\",\"revision_id\":\"33333333333333333333333333333333\",\"source_hash\":\"3333333333333333333333333333333333333333333333333333333333333333\",\"canonical_hash\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"}]}\n","audits":[{"events":[{"type":"snapshot","mode":"initializing"},{"type":"transaction-created","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"get-success","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"put-success","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"transaction-complete","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"snapshot","mode":"persistent"},{"type":"transaction-created","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"get-success","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"transaction-complete","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"connection-close","connection":2,"version":1}],"snapshot":["persistent",[[0,1],[2]],""]}],"closed":[[10,[{"type":"connection-close","connection":1,"version":1},{"type":"fixture-closed"}],["persistent",[[0,1],[2]],""]]]},
"commit-notification-failure":{"before":[[0,[[],[]]]],"after":[[1,[[0],[]]]],"fault":"BroadcastChannel.prototype.postMessage throws after native command transaction complete","outcomes":["committed"],"audits":[{"events":[{"type":"snapshot","mode":"initializing"},{"type":"transaction-created","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"get-success","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"put-success","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"transaction-complete","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"snapshot","mode":"persistent"},{"type":"transaction-created","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"get-success","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"transaction-complete","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"connection-close","connection":2,"version":1},{"type":"arm-post-failure"},{"type":"command-start","index":0},{"type":"transaction-created","tx":3,"connection":1,"label":"command","mode":"readwrite"},{"type":"get-success","tx":3,"connection":1,"label":"command","mode":"readwrite"},{"type":"put-success","tx":3,"connection":1,"label":"command","mode":"readwrite"},{"type":"transaction-complete","tx":3,"connection":1,"label":"command","mode":"readwrite"},{"type":"snapshot","mode":"persistent"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"production"},{"type":"notification-post-threw"},{"type":"snapshot","mode":"persistent"},{"type":"command-outcome","index":0,"outcome":"committed"},{"type":"transaction-created","tx":4,"connection":3,"label":"command","mode":"readonly"},{"type":"get-success","tx":4,"connection":3,"label":"command","mode":"readonly"},{"type":"transaction-complete","tx":4,"connection":3,"label":"command","mode":"readonly"},{"type":"connection-close","connection":3,"version":1}],"snapshot":["persistent",[[0],[]],"Library notification unavailable; refresh on focus remains available."]}],"closed":[[25,[{"type":"connection-close","connection":1,"version":1},{"type":"fixture-closed"}],["persistent",[[0],[]],"Library notification unavailable; refresh on focus remains available."]]]},
"request-success-then-abort":{"before":[[0,[[],[]]]],"after":[[0,[[],[]]]],"fault":"native put success listener calls same transaction.abort before complete","outcomes":["unavailable"],"audits":[{"events":[{"type":"snapshot","mode":"initializing"},{"type":"transaction-created","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"get-success","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"put-success","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"transaction-complete","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"snapshot","mode":"persistent"},{"type":"transaction-created","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"get-success","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"transaction-complete","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"connection-close","connection":2,"version":1},{"type":"arm-abort"},{"type":"command-start","index":0},{"type":"transaction-created","tx":3,"connection":1,"label":"command","mode":"readwrite"},{"type":"get-success","tx":3,"connection":1,"label":"command","mode":"readwrite"},{"type":"put-success","tx":3,"connection":1,"label":"command","mode":"readwrite"},{"type":"abort-after-put-success","tx":3,"connection":1,"label":"command","mode":"readwrite"},{"type":"transaction-abort","tx":3,"connection":1,"label":"command","mode":"readwrite"},{"type":"connection-close","connection":1,"version":1},{"type":"snapshot","mode":"memory"},{"type":"command-outcome","index":0,"outcome":"unavailable"},{"type":"transaction-created","tx":4,"connection":3,"label":"command","mode":"readonly"},{"type":"get-success","tx":4,"connection":3,"label":"command","mode":"readonly"},{"type":"transaction-complete","tx":4,"connection":3,"label":"command","mode":"readonly"},{"type":"connection-close","connection":3,"version":1}],"snapshot":["memory",[[],[]],"Library preferences unavailable; using memory for this mount."]}],"closed":[[24,[{"type":"connection-close","connection":1,"version":1},{"type":"fixture-closed"}],["memory",[[],[]],"Library preferences unavailable; using memory for this mount."]]]},
"blocked-open-late-success":{"before":[[0,[[],[]]]],"after":[[0,[[],[]]]],"fault":"bounded factory version fault: production requested v1, native request v2 behind held v1; late upgrade abort, NOT late success","blocked":{"cut":[0,13,["memory",[[],[]],"Library preferences unavailable; using memory for this mount."]]},"outcomes":["memory"],"databases":[{"name":"arena-workbench-ui","version":1}],"audits":[{"events":[{"type":"transaction-created","tx":1,"connection":1,"label":"seed","mode":"readwrite"},{"type":"put-success","tx":1,"connection":1,"label":"seed","mode":"readwrite"},{"type":"transaction-complete","tx":1,"connection":1,"label":"seed","mode":"readwrite"},{"type":"connection-close","connection":1,"version":1},{"type":"transaction-created","tx":2,"connection":2,"label":"seed","mode":"readonly"},{"type":"get-success","tx":2,"connection":2,"label":"seed","mode":"readonly"},{"type":"transaction-complete","tx":2,"connection":2,"label":"seed","mode":"readonly"},{"type":"connection-close","connection":2,"version":1},{"type":"snapshot","mode":"initializing"},{"type":"factory-version-fault","requested":1,"actual":2},{"type":"holder-versionchange","oldVersion":1,"newVersion":2},{"type":"open-blocked"},{"type":"snapshot","mode":"memory"},{"type":"command-start","index":0},{"type":"snapshot","mode":"memory"},{"type":"command-outcome","index":0,"outcome":"memory"},{"type":"connection-close","connection":3,"version":1},{"type":"holder-released"},{"type":"late-upgradeneeded"},{"type":"late-upgrade-abort"},{"type":"open-error","name":"AbortError"},{"type":"transaction-created","tx":3,"connection":4,"label":"refresh","mode":"readonly"},{"type":"get-success","tx":3,"connection":4,"label":"refresh","mode":"readonly"},{"type":"transaction-complete","tx":3,"connection":4,"label":"refresh","mode":"readonly"},{"type":"connection-close","connection":4,"version":1}],"snapshot":["memory",[[0],[]],"Library preferences unavailable; using memory for this mount."]}],"closed":[[25,[{"type":"fixture-closed"}],["memory",[[0],[]],"Library preferences unavailable; using memory for this mount."]]]},
"versionchange":{"before":[[0,[[],[]]]],"after":[[0,[[],[]]]],"retired":{"cut":[0,16,["memory",[[],[]],"Library preferences unavailable; using memory for this mount."]]},"outcomes":["memory"],"databases":[{"name":"arena-workbench-ui","version":2}],"audits":[{"events":[{"type":"snapshot","mode":"initializing"},{"type":"transaction-created","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"get-success","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"put-success","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"transaction-complete","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"snapshot","mode":"persistent"},{"type":"transaction-created","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"get-success","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"transaction-complete","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"connection-close","connection":2,"version":1},{"type":"connection-close","connection":1,"version":1},{"type":"connection-close","connection":1,"version":1},{"type":"snapshot","mode":"memory"},{"type":"native-versionchange","connection":1,"oldVersion":1,"newVersion":2},{"type":"independent-upgrade-complete","version":2},{"type":"connection-close","connection":3,"version":2},{"type":"command-start","index":0},{"type":"snapshot","mode":"memory"},{"type":"command-outcome","index":0,"outcome":"memory"},{"type":"transaction-created","tx":3,"connection":4,"label":"refresh","mode":"readonly"},{"type":"get-success","tx":3,"connection":4,"label":"refresh","mode":"readonly"},{"type":"transaction-complete","tx":3,"connection":4,"label":"refresh","mode":"readonly"},{"type":"connection-close","connection":4,"version":2}],"snapshot":["memory",[[0],[]],"Library preferences unavailable; using memory for this mount."]}],"closed":[[23,[{"type":"connection-close","connection":1,"version":1},{"type":"fixture-closed"}],["memory",[[0],[]],"Library preferences unavailable; using memory for this mount."]]]},
"missing-record":{"before":[[0,[[],[]]]],"after":[{"state":"absent-record","raw":null,"settledBy":"transaction.oncomplete"}],"deleted":{"state":"absent-record","raw":null,"settledBy":"transaction.oncomplete"},"outcomes":["memory"],"audits":[{"events":[{"type":"snapshot","mode":"initializing"},{"type":"transaction-created","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"get-success","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"put-success","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"transaction-complete","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"snapshot","mode":"persistent"},{"type":"transaction-created","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"get-success","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"transaction-complete","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"connection-close","connection":2,"version":1},{"type":"transaction-created","tx":3,"connection":3,"label":"delete-record","mode":"readwrite"},{"type":"transaction-complete","tx":3,"connection":3,"label":"delete-record","mode":"readwrite"},{"type":"connection-close","connection":3,"version":1},{"type":"transaction-created","tx":4,"connection":4,"label":"delete-record","mode":"readonly"},{"type":"get-success","tx":4,"connection":4,"label":"delete-record","mode":"readonly"},{"type":"transaction-complete","tx":4,"connection":4,"label":"delete-record","mode":"readonly"},{"type":"connection-close","connection":4,"version":1},{"type":"transaction-created","tx":5,"connection":1,"label":"refresh","mode":"readonly"},{"type":"get-success","tx":5,"connection":1,"label":"refresh","mode":"readonly"},{"type":"transaction-abort","tx":5,"connection":1,"label":"refresh","mode":"readonly"},{"type":"connection-close","connection":1,"version":1},{"type":"snapshot","mode":"memory"},{"type":"command-start","index":0},{"type":"snapshot","mode":"memory"},{"type":"command-outcome","index":0,"outcome":"memory"},{"type":"transaction-created","tx":6,"connection":5,"label":"refresh","mode":"readonly"},{"type":"get-success","tx":6,"connection":5,"label":"refresh","mode":"readonly"},{"type":"transaction-complete","tx":6,"connection":5,"label":"refresh","mode":"readonly"},{"type":"connection-close","connection":5,"version":1}],"snapshot":["memory",[[0],[]],"Library preferences unavailable; using memory for this mount."]}],"closed":[[29,[{"type":"connection-close","connection":1,"version":1},{"type":"fixture-closed"}],["memory",[[0],[]],"Library preferences unavailable; using memory for this mount."]]]},
"notification-no-authority":{"before":[[0,[[],[]]]],"after":[[0,[[],[]]]],"payloads":[{"revision":999,"preferences":{"pins":[{"id":"editor-revision:11111111111111111111111111111111","kind":"editor_revision","revision_id":"11111111111111111111111111111111","source_hash":"1111111111111111111111111111111111111111111111111111111111111111","canonical_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]}},{"type":"library-preferences-changed/v1","revision":999},"foreign",null],"beforeMessages":{"cut":[0,10,["persistent",[[],[]],""]]},"invalidDelivered":{"cut":[0,18,["persistent",[[],[]],""]]},"beforeHints":{"cut":[0,20,["persistent",[[],[]],""]]},"heldHints":{"cut":[0,53,["persistent",[[],[]],""]]},"afterHints":{"cut":[0,62,["persistent",[[],[]],""]]},"uiBefore":{"openRequests":"0","pinDisabled":true,"pins":"Pinned revisions\n\nNo pinned revisions."},"uiRecord":[0,[[],[]]],"uiAfter":{"openRequests":"0","pinDisabled":true,"pins":"Pinned revisions\n\nNo pinned revisions."},"audits":[{"events":[{"type":"snapshot","mode":"initializing"},{"type":"transaction-created","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"get-success","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"put-success","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"transaction-complete","tx":1,"connection":1,"label":"initialize","mode":"readwrite"},{"type":"snapshot","mode":"persistent"},{"type":"transaction-created","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"get-success","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"transaction-complete","tx":2,"connection":2,"label":"initialize","mode":"readonly"},{"type":"connection-close","connection":2,"version":1},{"type":"notification-post","message":{"revision":999,"preferences":{"pins":[{"id":"editor-revision:11111111111111111111111111111111","kind":"editor_revision","revision_id":"11111111111111111111111111111111","source_hash":"1111111111111111111111111111111111111111111111111111111111111111","canonical_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]}},"source":"fixture-sender"},{"type":"notification-post","message":{"type":"library-preferences-changed/v1","revision":999},"source":"fixture-sender"},{"type":"notification-post","message":"foreign","source":"fixture-sender"},{"type":"notification-post","message":null,"source":"fixture-sender"},{"type":"message-delivered","data":{"revision":999,"preferences":{"pins":[{"id":"editor-revision:11111111111111111111111111111111","kind":"editor_revision","revision_id":"11111111111111111111111111111111","source_hash":"1111111111111111111111111111111111111111111111111111111111111111","canonical_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]}}},{"type":"message-delivered","data":{"type":"library-preferences-changed/v1","revision":999}},{"type":"message-delivered","data":"foreign"},{"type":"message-delivered","data":null},{"type":"transaction-created","tx":3,"connection":3,"label":"barrier","mode":"readwrite"},{"type":"barrier-active"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"fixture-sender"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"fixture-sender"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"fixture-sender"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"fixture-sender"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"fixture-sender"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"fixture-sender"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"fixture-sender"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"fixture-sender"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"fixture-sender"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"fixture-sender"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"fixture-sender"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"fixture-sender"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"fixture-sender"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"fixture-sender"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"fixture-sender"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"fixture-sender"},{"type":"transaction-created","tx":4,"connection":1,"label":"barrier","mode":"readonly"},{"type":"message-delivered","data":"library-preferences-changed/v1"},{"type":"message-delivered","data":"library-preferences-changed/v1"},{"type":"message-delivered","data":"library-preferences-changed/v1"},{"type":"message-delivered","data":"library-preferences-changed/v1"},{"type":"message-delivered","data":"library-preferences-changed/v1"},{"type":"message-delivered","data":"library-preferences-changed/v1"},{"type":"message-delivered","data":"library-preferences-changed/v1"},{"type":"message-delivered","data":"library-preferences-changed/v1"},{"type":"message-delivered","data":"library-preferences-changed/v1"},{"type":"message-delivered","data":"library-preferences-changed/v1"},{"type":"message-delivered","data":"library-preferences-changed/v1"},{"type":"message-delivered","data":"library-preferences-changed/v1"},{"type":"message-delivered","data":"library-preferences-changed/v1"},{"type":"message-delivered","data":"library-preferences-changed/v1"},{"type":"message-delivered","data":"library-preferences-changed/v1"},{"type":"message-delivered","data":"library-preferences-changed/v1"},{"type":"barrier-release","count":84},{"type":"transaction-complete","tx":3,"connection":3,"label":"barrier","mode":"readwrite"},{"type":"connection-close","connection":3,"version":1},{"type":"barrier-complete","count":85},{"type":"get-success","tx":4,"connection":1,"label":"barrier","mode":"readonly"},{"type":"transaction-complete","tx":4,"connection":1,"label":"barrier","mode":"readonly"},{"type":"transaction-created","tx":5,"connection":1,"label":"barrier","mode":"readonly"},{"type":"get-success","tx":5,"connection":1,"label":"barrier","mode":"readonly"},{"type":"transaction-complete","tx":5,"connection":1,"label":"barrier","mode":"readonly"},{"type":"transaction-created","tx":6,"connection":4,"label":"barrier","mode":"readonly"},{"type":"get-success","tx":6,"connection":4,"label":"barrier","mode":"readonly"},{"type":"transaction-complete","tx":6,"connection":4,"label":"barrier","mode":"readonly"},{"type":"connection-close","connection":4,"version":1},{"type":"transaction-created","tx":7,"connection":1,"label":"barrier","mode":"readonly"},{"type":"get-success","tx":7,"connection":1,"label":"barrier","mode":"readonly"},{"type":"transaction-complete","tx":7,"connection":1,"label":"barrier","mode":"readonly"}],"snapshot":["persistent",[[],[]],""]},{"events":[{"type":"transaction-created","tx":1,"connection":1,"label":"fixture","mode":"readwrite"},{"type":"get-success","tx":1,"connection":1,"label":"fixture","mode":"readwrite"},{"type":"transaction-complete","tx":1,"connection":1,"label":"fixture","mode":"readwrite"},{"type":"notification-post","message":{"revision":999,"preferences":{"pins":[{"id":"editor-revision:11111111111111111111111111111111","kind":"editor_revision","revision_id":"11111111111111111111111111111111","source_hash":"1111111111111111111111111111111111111111111111111111111111111111","canonical_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]}},"source":"fixture-sender"},{"type":"notification-post","message":{"type":"library-preferences-changed/v1","revision":999},"source":"fixture-sender"},{"type":"notification-post","message":"foreign","source":"fixture-sender"},{"type":"notification-post","message":null,"source":"fixture-sender"},{"type":"notification-post","message":"library-preferences-changed/v1","source":"fixture-sender"},{"type":"message-delivered","data":{"revision":999,"preferences":{"pins":[{"id":"editor-revision:11111111111111111111111111111111","kind":"editor_revision","revision_id":"11111111111111111111111111111111","source_hash":"1111111111111111111111111111111111111111111111111111111111111111","canonical_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]}}},{"type":"message-delivered","data":{"type":"library-preferences-changed/v1","revision":999}},{"type":"message-delivered","data":"foreign"},{"type":"message-delivered","data":null},{"type":"transaction-created","tx":2,"connection":1,"label":"fixture","mode":"readonly"},{"type":"message-delivered","data":"library-preferences-changed/v1"},{"type":"get-success","tx":2,"connection":1,"label":"fixture","mode":"readonly"},{"type":"transaction-complete","tx":2,"connection":1,"label":"fixture","mode":"readonly"},{"type":"transaction-created","tx":3,"connection":2,"label":"fixture","mode":"readonly"},{"type":"get-success","tx":3,"connection":2,"label":"fixture","mode":"readonly"},{"type":"transaction-complete","tx":3,"connection":2,"label":"fixture","mode":"readonly"},{"type":"connection-close","connection":2,"version":1}],"snapshot":null}],"closed":[[69,[{"type":"connection-close","connection":1,"version":1},{"type":"fixture-closed"}],["persistent",[[],[]],""]],[20,[{"type":"connection-close","connection":1,"version":1},{"type":"fixture-closed"}],null]]}
}''')
    refs = [{'id': 'editor-revision:' + d * 32, 'kind': 'editor_revision', 'revision_id': d * 32,
             'source_hash': d * 64, 'canonical_hash': 'a' * 64} for d in '123456789']
    def preferences(value):
        return {'version': 1, 'pins': [refs[i] for i in value[0]], 'recents': [refs[i] for i in value[1]]}
    def snapshot(value):
        return None if value is None else {'mode': value[0], 'preferences': preferences(value[1]), 'notice': value[2]}
    def observation(value):
        if type(value) is dict: return value
        return {'state': 'record', 'settledBy': 'transaction.oncomplete', 'raw': json.dumps({
            'schemaVersion': 1, 'revision': value[0], 'preferences': preferences(value[1])})}
    def audit(events, value):
        return {'events': [dict(e, seq=i + 1) for i, e in enumerate(events)], 'snapshot': snapshot(value), 'overflow': False}
    for name, row in data.items():
        row.update(id=name, schema=2, status='observed', isolation='fresh-browser-context',
                   scope='native production controller; synthetic editor references/admission; no API/source authority',
                   browser_version='synthetic-not-a-browser-run', bounds={'barrier_ms': 4000, 'barrier_requests': 100000, 'events_per_page': 512},
                   cleanup_verified=True, initial={'state': 'absent-database'})
        if name == 'legacy-exact-unchanged':
            row['initWitness'] = dict(phase='playwright-init-script', readyState='loading', scripts=0,
                                      fixturePresent=False, raw=row['legacyBefore'], verifiedRaw=row['legacyBefore'])
            row['moduleEntry'] = dict(phase='fixture-module-entry', raw=row['legacyBefore'], initSeen=True)
        row['audits'] = [audit(a['events'], a['snapshot']) for a in row['audits']]
        row['closed'] = [audit(a['events'][:n] + suffix, value) for a, (n, suffix, value) in zip(row['audits'], row['closed'])]
        def cut(value):
            page, n, state = value['cut']
            return audit(row['audits'][page]['events'][:n], state)
        for key, value in list(row.items()):
            if type(value) is dict and set(value) == {'cut'}: row[key] = cut(value)
            elif key == 'queued': row[key] = [cut(v) for v in value]
        row['before'] = [observation(o) for o in row['before']]
        row['after'] = [observation(o) for o in row['after']]
        if 'uiRecord' in row:
            row['uiRecord'] = observation(row['uiRecord'])
            ready = next(e['seq'] for e in row['audits'][1]['events'] if e['type'] == 'transaction-complete' and e['mode'] == 'readwrite')
            row['uiReady'] = audit(row['audits'][1]['events'][:ready], None)
        if name == 'missing-record':
            for value in (row['audits'][0], row['closed'][0]):
                events = []
                for e in value['events']:
                    if e['type'] == 'transaction-complete' and e.get('mode') == 'readwrite' and e.get('label') == 'delete-record':
                        events.append(dict(e, type='delete-success', key='default', store='libraryPreferences'))
                    events.append(e)
                value['events'] = [dict(e, seq=i + 1) for i, e in enumerate(events)]
        if name == 'notification-no-authority':
            # Synthetic production-delivery witness before each production read.
            # All prefix and closed copies receive the same inserted event.
            def delivery(value):
                if type(value) is dict:
                    if set(value) == {'events', 'snapshot', 'overflow'}:
                        events = []
                        for e in value['events']:
                            if e['type'] == 'transaction-created' and e.get('mode') == 'readonly' and e.get('connection') == 1:
                                events.append(dict(type='production-message', data='library-preferences-changed/v1'))
                            events.append(e)
                        value['events'] = [dict(e, seq=i + 1) for i, e in enumerate(events)]
                    else:
                        for item in value.values(): delivery(item)
                elif type(value) is list:
                    for item in value: delivery(item)
            delivery(row)
        # Expand v2 connection roles and observer-event identities. These are
        # explicitly synthetic values, not newly obtained native execution.
        for page, final in enumerate(row['audits']):
            fixture_connections = {e['connection'] for e in final['events'] if e.get('mode') == 'readwrite' and e.get('label') in ('seed', 'barrier', 'delete-record')}
            production_connections = {e['connection'] for e in final['events'] if e.get('mode') == 'readwrite' and e.get('label') not in ('seed', 'barrier', 'delete-record')}
            all_audits = [final, row['closed'][page]]
            for key, value in row.items():
                if key not in ('audits', 'closed'):
                    candidates = value if key == 'queued' else [value]
                    for candidate in candidates:
                        if type(candidate) is dict and 'events' in candidate and candidate['events'] == final['events'][:len(candidate['events'])]:
                            all_audits.append(candidate)
            observations = ([row['uiRecord']] if page == 1 and 'uiRecord' in row else
                            ([row['before'][page]] if row['before'] else []) +
                            ([row['deleted']] if 'deleted' in row else []) + [row['after'][page]])
            observer_txs = [e for e in final['events'] if e['type'] == 'transaction-created' and e['connection'] not in fixture_connections | production_connections]
            assert len(observer_txs) == len(observations), (name, page)
            raw_by_tx = {}
            for observation_value, created in zip(observations, observer_txs):
                tx = created['tx']
                identity = lambda kind: next(e['seq'] for e in final['events'] if e.get('tx') == tx and e['type'] == kind)
                observation_value['binding'] = dict(connection=created['connection'], tx=tx, created=created['seq'], get=identity('get-success'), complete=identity('transaction-complete'))
                raw_by_tx[tx] = observation_value['raw']
            for value in all_audits:
                for e in value['events']:
                    if 'tx' not in e: continue
                    e['role'] = 'fixture' if e['connection'] in fixture_connections else 'production' if e['connection'] in production_connections else 'observer'
                    if e['type'] == 'get-success' and e['role'] == 'observer': e['raw'] = raw_by_tx[e['tx']]
                    if e['type'] == 'get-success' and e['role'] == 'production' and e['mode'] == 'readonly':
                        e['raw'] = row['after'][0]['raw']
                    if e['type'] == 'put-success' and e['label'] == 'seed': e['raw'] = row['before'][0]['raw']
        # Synthetic JSON formatting is intentionally not native byte provenance.
    return copy.deepcopy(data)


class PipeProcess:
    """Real pipe descriptors, synthetic process identity; never spawns a child."""
    def __init__(self, out, err, *, hold=False, kill_error=False, wait_error=False, exit_code=2):
        import os
        self.returncode = None
        self.exit_code = exit_code
        self.kills = self.waits = 0
        self.kill_error, self.wait_error = kill_error, wait_error
        self.writers = []
        readers = []
        for raw in (out, err):
            reader, writer = os.pipe()
            readers.append(os.fdopen(reader, 'rb', buffering=0))
            os.write(writer, raw)
            if hold: self.writers.append(writer)
            else: os.close(writer)
        self.stdout, self.stderr = readers

    def kill(self):
        self.kills += 1
        if self.kill_error: raise OSError('synthetic private kill error')
        self.returncode = -9

    def wait(self, timeout):
        import subprocess
        self.waits += 1
        if self.wait_error: raise subprocess.TimeoutExpired('synthetic private argv', timeout)
        if self.returncode is None: self.returncode = self.exit_code
        return self.returncode

    def close(self):
        import os
        for writer in self.writers: os.close(writer)
        self.stdout.close(); self.stderr.close()


class StorageProbeChecks(unittest.TestCase):
    def test_candidate_resealed_case_witness_negatives(self):
        import copy
        import json
        def rewrite(row, transform):
            # Update every prefix/final/closed copy coherently: rejection must not
            # depend merely on an unresealed hash or a stale duplicate audit.
            def walk(value):
                if type(value) is dict:
                    if set(value) == {'events', 'snapshot', 'overflow'}:
                        value['events'] = [new for e in value['events'] if (new := transform(copy.deepcopy(e))) is not None]
                        for index, event in enumerate(value['events']): event['seq'] = index + 1
                    else:
                        for item in value.values(): walk(item)
                elif type(value) is list:
                    for item in value: walk(item)
            walk(row)
            # Resequence surviving read bindings too; deleted witnesses remain
            # dangling deliberately, but unrelated offsets cannot cause rejection.
            for page, audit in enumerate(row['closed']):
                observations = ([row['uiRecord']] if page == 1 and 'uiRecord' in row else
                                ([row['before'][page]] if row['before'] else []) +
                                ([row['deleted']] if 'deleted' in row else []) + [row['after'][page]])
                for observation in observations:
                    binding = observation.get('binding', {})
                    for field, kind in [('created', 'transaction-created'), ('get', 'get-success'), ('complete', 'transaction-complete')]:
                        found = [e for e in audit['events'] if e.get('tx') == binding.get('tx') and e['type'] == kind]
                        if len(found) == 1: binding[field] = found[0]['seq']
        def drop(kind): return lambda row: rewrite(row, lambda e: None if e['type'] == kind else e)
        def suffix(row, events):
            trace = row['closed'][0]['events']
            trace[-1:-1] = copy.deepcopy(events)
            for index, event in enumerate(trace): event['seq'] = index + 1
        def move(row, predicate, target):
            original = copy.deepcopy(row['audits'][0]['events'])
            moved = [e for e in original if predicate(e)]
            rest = [e for e in original if not predicate(e)]
            index = next(i for i, e in enumerate(rest) if target(e))
            reordered = rest[:index] + moved + rest[index:]
            def walk(value):
                if type(value) is dict:
                    if set(value) == {'events', 'snapshot', 'overflow'}:
                        n = len(value['events'])
                        if value['events'][:min(n, len(original))] == original[:min(n, len(original))]:
                            value['events'] = copy.deepcopy(reordered[:n] + value['events'][len(original):])
                    else:
                        for item in value.values(): walk(item)
                elif type(value) is list:
                    for item in value: walk(item)
            walk(row); rewrite(row, lambda e: e)
        def extra_initial_put(row):
            def walk(value):
                if type(value) is dict:
                    if set(value) == {'events', 'snapshot', 'overflow'}:
                        events = []
                        for e in value['events']:
                            if e['type'] == 'transaction-complete' and e.get('mode') == 'readwrite' and e.get('label') == 'initialize':
                                events.append(dict(e, type='put-success', raw='{}'))
                            events.append(e)
                        value['events'] = events
                    else:
                        for item in value.values(): walk(item)
                elif type(value) is list:
                    for item in value: walk(item)
            walk(row); rewrite(row, lambda e: e)
        def remove_ui_refresh(row):
            for audit in (row['audits'][1], row['closed'][1]):
                audit['events'] = [e for e in audit['events'] if not (e.get('mode') == 'readonly' and e.get('role') == 'production')]
            rewrite(row, lambda e: e)
        late_write = [dict(type=kind, tx=99, connection=99, label='late', mode='readwrite', role='fixture')
                      for kind in ('transaction-created', 'put-success', 'transaction-complete')]
        mutations = [
            ('missing-record', 'production missing read absent', lambda r: rewrite(r, lambda e: None if e['type'] == 'get-success' and e.get('role') == 'production' and e.get('mode') == 'readonly' else e)),
            ('missing-record', 'production missing read contradicts absence', lambda r: rewrite(r, lambda e: dict(e, raw=r['before'][0]['raw']) if e['type'] == 'get-success' and e.get('role') == 'production' and e.get('mode') == 'readonly' else e)),
            ('versionchange', 'upgrade completes before native versionchange', lambda r: move(r, lambda e: e['type'] == 'independent-upgrade-complete', lambda e: e['type'] == 'native-versionchange')),
            ('versionchange', 'retired cut precedes versionchange witnesses', lambda r: r['retired'].update(events=r['retired']['events'][:13])),
            ('versionchange', 'observer substituted for initialized connection', lambda r: rewrite(r, lambda e: dict(e, connection=r['before'][0]['binding']['connection']) if e['type'] == 'native-versionchange' else e)),
            ('blocked-open-late-success', 'completed observer terminal deleted', lambda r: rewrite(r, lambda e: None if e['type'] == 'transaction-complete' and e.get('role') == 'observer' else e)),
            ('blocked-open-late-success', 'observer get reordered before creation', lambda r: move(r, lambda e: e['type'] == 'get-success' and e.get('tx') == r['before'][0]['binding']['tx'], lambda e: e['type'] == 'transaction-created' and e.get('tx') == r['before'][0]['binding']['tx'])),
            ('blocked-open-late-success', 'before after readback swapped', lambda r: r.update(before=r['after'], after=r['before'])),
            ('blocked-open-late-success', 'unbound before readback', lambda r: r['before'][0].pop('binding')),
            ('blocked-open-late-success', 'wrong readback connection', lambda r: r['after'][0]['binding'].update(connection=99)),
            ('blocked-open-late-success', 'wrong readback transaction', lambda r: r['after'][0]['binding'].update(tx=99)),
            ('blocked-open-late-success', 'wrong readback get identity', lambda r: r['after'][0]['binding'].update(get=1)),
            ('blocked-open-late-success', 'wrong readback terminal identity', lambda r: r['after'][0]['binding'].update(complete=1)),
            ('blocked-open-late-success', 'observer raw contradiction', lambda r: rewrite(r, lambda e: dict(e, raw='{}') if e['type'] == 'get-success' and e.get('role') == 'observer' else e)),
            ('blocked-open-late-success', 'observer role substitution', lambda r: rewrite(r, lambda e: dict(e, role='fixture') if e.get('role') == 'observer' else e)),
            ('legacy-exact-unchanged', 'orphan bound terminal', lambda r: suffix(r, [dict(type='transaction-complete', tx=99, connection=99, label='refresh', mode='readonly', role='production')])),
            ('legacy-exact-unchanged', 'unsettled cleanup readonly', lambda r: suffix(r, [dict(type='transaction-created', tx=99, connection=99, label='refresh', mode='readonly', role='production')])),
            ('legacy-exact-unchanged', 'module entry before seed', lambda r: r['moduleEntry'].update(initSeen=False)),
            ('legacy-exact-unchanged', 'late init script', lambda r: r['initWitness'].update(scripts=1)),
            ('legacy-exact-unchanged', 'init readback bytes', lambda r: r['initWitness'].update(verifiedRaw='{}')),
            ('notification-no-authority', 'production delivery missing', drop('production-message')),
            ('competing-pins-at-capacity', 'extra write inside initialize', extra_initial_put),
            ('missing-record', 'native delete request missing', drop('delete-success')),
            ('competing-pins-at-capacity', 'awaited initialize aborted', lambda r: rewrite(r, lambda e: dict(e, type='transaction-abort') if e['type'] == 'transaction-complete' and e.get('label') == 'initialize' and e.get('role') == 'production' else e)),
            ('competing-pins-at-capacity', 'seed put raw contradiction', lambda r: rewrite(r, lambda e: dict(e, raw='{}') if e['type'] == 'put-success' and e.get('label') == 'seed' else e)),
            ('notification-no-authority', 'production refresh raw contradiction', lambda r: rewrite(r, lambda e: dict(e, raw='{}') if e['type'] == 'get-success' and e.get('role') == 'production' and e.get('mode') == 'readonly' else e)),
            ('two-pages-concurrent-pins', 'notify before commit', lambda r: move(r, lambda e: e['type'] == 'notification-post', lambda e: e['type'] == 'transaction-complete' and e.get('label') == 'command')),
            ('blocked-open-late-success', 'command before blocked fallback', lambda r: move(r, lambda e: e['type'] == 'command-start', lambda e: e['type'] == 'open-blocked')),
            ('blocked-open-late-success', 'holder released before memory command', lambda r: move(r, lambda e: e['type'] == 'holder-released', lambda e: e['type'] == 'command-start')),
            ('versionchange', 'command before retirement', lambda r: move(r, lambda e: e['type'] == 'command-start', lambda e: e['type'] == 'native-versionchange')),
            ('missing-record', 'delete terminal after conflict', lambda r: move(r, lambda e: e['type'] == 'transaction-complete' and e.get('label') == 'delete-record' and e.get('mode') == 'readwrite', lambda e: e['type'] == 'command-start')),
            ('notification-no-authority', 'observer cannot mask missing UI refresh', remove_ui_refresh),
            ('notification-no-authority', 'equally nonempty shelves', lambda r: (r['uiBefore'].update(pins='Pinned revisions: injected pin'), r['uiAfter'].update(pins='Pinned revisions: injected pin'))),
            ('legacy-exact-unchanged', 'pre-module seed witness', lambda r: r.pop('initWitness', None)),
            ('competing-pins-at-capacity', 'observer read missing', lambda r: rewrite(r, lambda e: None if e.get('mode') == 'readonly' and e.get('connection') == 3 and e['type'] == 'get-success' else e)),
            ('blocked-open-late-success', 'observer transaction absent', lambda r: rewrite(r, lambda e: None if e.get('mode') == 'readonly' and 'tx' in e else e)),
            *[(case, 'post-audit write', lambda r: suffix(r, late_write)) for case in probe.REQUIRED_CASES],
            *[(case, 'post-audit rebroadcast', lambda r: suffix(r, [dict(type='notification-post', source='production', message='library-preferences-changed/v1')])) for case in probe.REQUIRED_CASES],
            ('legacy-exact-unchanged', 'orphan terminal without identity', lambda r: suffix(r, [dict(type='transaction-complete')])),
            ('legacy-exact-unchanged', 'event after closure', lambda r: r['closed'][0]['events'].append(dict(type='connection-close', connection=1, version=1, seq=len(r['closed'][0]['events']) + 1))),
            ('competing-pins-at-capacity', 'seed completion', lambda r: rewrite(r, lambda e: None if e.get('label') == 'seed' and e['type'] in ('put-success', 'transaction-complete') else e)),
            ('blocked-open-late-success', 'seed completion', lambda r: rewrite(r, lambda e: None if e.get('label') == 'seed' and e.get('mode') == 'readwrite' and e['type'] == 'transaction-complete' else e)),
            ('two-pages-concurrent-pins', 'barrier active', drop('barrier-active')),
            ('two-pages-concurrent-pins', 'barrier release', drop('barrier-release')),
            ('two-pages-concurrent-pins', 'native completion', drop('barrier-complete')),
            ('two-pages-concurrent-pins', 'queued pair', lambda r: r.update(queued=r['queued'][:1])),
            ('competing-pins-at-capacity', 'loser limit', lambda r: r.update(outcomes=['committed', 'unavailable'])),
            ('competing-pins-at-capacity', 'seed pins', lambda r: r['before'][0].update(raw=r['after'][0]['raw'])),
            ('legacy-exact-unchanged', 'legacy bytes', lambda r: r.update(legacyAfter=r['legacyBefore'] + ' ')),
            ('legacy-exact-unchanged', 'before mount', lambda r: r['preMount'].update(snapshot={})),
            ('legacy-exact-unchanged', 'native put', drop('put-success')),
            ('commit-notification-failure', 'post threw', drop('notification-post-threw')),
            ('commit-notification-failure', 'post attempted', drop('notification-post')),
            ('commit-notification-failure', 'fault armed', drop('arm-post-failure')),
            ('request-success-then-abort', 'abort hook', drop('abort-after-put-success')),
            ('request-success-then-abort', 'abort terminal', drop('transaction-abort')),
            ('request-success-then-abort', 'put success', lambda r: rewrite(r, lambda e: None if e['type'] == 'put-success' and e['label'] == 'command' else e)),
            ('request-success-then-abort', 'outcome', lambda r: r.update(outcomes=['committed'])),
            ('blocked-open-late-success', 'fault label', lambda r: r.pop('fault')),
            ('blocked-open-late-success', 'native blocked', drop('open-blocked')),
            ('blocked-open-late-success', 'native late upgrade', drop('late-upgradeneeded')),
            ('blocked-open-late-success', 'late abort', drop('late-upgrade-abort')),
            ('blocked-open-late-success', 'version result', lambda r: r['databases'][0].update(version=2)),
            ('versionchange', 'native event', drop('native-versionchange')),
            ('versionchange', 'connection close', drop('connection-close')),
            ('versionchange', 'upgrade complete', drop('independent-upgrade-complete')),
            ('missing-record', 'deleted witness', lambda r: r.pop('deleted')),
            ('missing-record', 'disappearance', lambda r: r.update(after=r['before'])),
            ('notification-no-authority', 'native delivery', drop('message-delivered')),
            ('notification-no-authority', 'held hint', lambda r: r.pop('heldHints')),
            ('notification-no-authority', 'trailing refresh', lambda r: r.update(afterHints=r['heldHints'])),
            ('notification-no-authority', 'UI ready', lambda r: r.pop('uiReady')),
            ('notification-no-authority', 'UI authority', lambda r: r['uiAfter'].update(pinDisabled=False)),
            ('notification-no-authority', 'UI Open', lambda r: r['uiAfter'].update(openRequests='1')),
        ]
        def verify(output, proof):
            self._seal_checker_fixture(output, proof)
            driver_path = output / 'evidence/storage-browser.json'
            driver = json.loads(driver_path.read_text())
            driver['result'].update(case_schema='native-storage-candidate/v2', cases=synthetic_native_cases())
            driver['required_cases'] = proof['required_cases'] = {name: 'observed' for name in probe.REQUIRED_CASES}
            def save(current, value):
                driver_path.write_text(json.dumps(value))
                for name, case in value['result']['cases'].items():
                    (output / ('evidence/native-case-' + name + '.json')).write_text(json.dumps(case))
                self._reseal(output, current)
            save(proof, driver)
            self.assertEqual(probe.check_storage_proof(output, require_complete=False)['candidate']['observed'], 9)
            with self.assertRaisesRegex(AssertionError, 'awaiting parent review'):
                probe.check_storage_proof(output)
            original = copy.deepcopy(proof)
            for case, description, mutate in mutations:
                with self.subTest(case=case, witness=description):
                    current, value = copy.deepcopy(original), copy.deepcopy(driver)
                    mutate(value['result']['cases'][case]); save(current, value)
                    with self.assertRaises(AssertionError): probe.check_storage_proof(output, require_complete=False)
            for name in probe.REQUIRED_CASES:
                with self.subTest(missing_case=name):
                    current, value = copy.deepcopy(original), copy.deepcopy(driver)
                    del value['result']['cases'][name]; save(current, value)
                    with self.assertRaisesRegex(AssertionError, 'native case set'):
                        probe.check_storage_proof(output, require_complete=False)
                with self.subTest(missing_artifact=name):
                    current, value = copy.deepcopy(original), copy.deepcopy(driver); save(current, value)
                    (output / ('evidence/native-case-' + name + '.json')).unlink(); self._reseal(output, current)
                    with self.assertRaisesRegex(AssertionError, 'missing native case artifact'):
                        probe.check_storage_proof(output, require_complete=False)
            current, value = copy.deepcopy(original), copy.deepcopy(driver); save(current, value)
            path = output / ('evidence/native-case-' + probe.REQUIRED_CASES[0] + '.json')
            record = json.loads(path.read_text()); record['browser_version'] = 'substituted'
            path.write_text(json.dumps(record)); self._reseal(output, current)
            with self.assertRaisesRegex(AssertionError, 'native case artifact mirror'):
                probe.check_storage_proof(output, require_complete=False)
        self._host_fixture(verify=verify)

    def test_native_candidate_synthetic_roundtrip_and_ui_delivery_witness(self):
        cases = synthetic_native_cases()
        self.assertEqual(probe.validate_native_cases(cases)['observed'], 9)
        row = cases['notification-no-authority']
        for audit in (row['audits'][1], row['closed'][1]):
            audit['events'] = [e for e in audit['events'] if e['type'] != 'message-delivered']
            for index, event in enumerate(audit['events']): event['seq'] = index + 1
        binding = row['uiRecord']['binding']
        for field, kind in [('created', 'transaction-created'), ('get', 'get-success'), ('complete', 'transaction-complete')]:
            binding[field] = next(e['seq'] for e in row['closed'][1]['events'] if e.get('tx') == binding['tx'] and e['type'] == kind)
        with self.assertRaisesRegex(AssertionError, 'native UI message delivery'):
            probe.validate_native_cases(cases)

    def test_native_candidate_requires_exact_case_witnesses(self):
        self.assertTrue(hasattr(probe, 'validate_native_cases'), 'native case witness checker missing')
        with self.assertRaisesRegex(AssertionError, 'native case set'):
            probe.validate_native_cases({})

    def test_safeunits_restores_process_hooks_on_success_failure_and_preassert(self):
        import self_test
        import run
        import sys
        sources, bootstrap = self_test.UNIT_SOURCES, self_test.NODE_UNITS
        docker, owned, argv = run.docker, run.OwnedRun, sys.argv
        for outcome in ('0', RuntimeError('mock Docker fault'), '0'):
            with self.subTest(outcome=str(outcome)), tempfile.TemporaryDirectory() as directory:
                managers = []
                def main():
                    manager = run.OwnedRun(Path(directory), 'mock-owned-unit')
                    managers.append(manager)
                    return int(run.docker('wait', 'a' * 64))
                with patch.object(run, 'docker') as daemon, patch.object(self_test, 'main', side_effect=main):
                    if isinstance(outcome, Exception):
                        daemon.side_effect = outcome
                        with self.assertRaisesRegex(RuntimeError, 'mock Docker fault'):
                            probe.safeunits(probe.STOPPED_FRONTEND)
                        self.assertEqual(managers[0].proof['unit_exits'], [
                            {'id': 'a' * 64, 'exit': None, 'error': 'RuntimeError'}])
                    else:
                        daemon.return_value = outcome
                        self.assertEqual(probe.safeunits(probe.STOPPED_FRONTEND), 0)
                        self.assertEqual(managers[0].proof['unit_exits'], [{'id': 'a' * 64, 'exit': outcome}])
                    daemon.assert_called_once_with('wait', 'a' * 64)
                    self.assertIs(run.docker, daemon)
                self.assertIs(self_test.UNIT_SOURCES, sources)
                self.assertEqual(self_test.NODE_UNITS, bootstrap)
                self.assertIs(run.docker, docker)
                self.assertIs(run.OwnedRun, owned)
                self.assertIs(sys.argv, argv)
        with patch.object(self_test, 'NODE_UNITS', 'changed bootstrap'):
            with self.assertRaisesRegex(AssertionError, 'bootstrap changed'):
                probe.safeunits(probe.STOPPED_FRONTEND)
            self.assertIs(self_test.UNIT_SOURCES, sources)
            self.assertEqual(self_test.NODE_UNITS, 'changed bootstrap')

    def test_owned_browser_lifecycle_preflight_is_real_bound_exec_before_driver(self):
        self.assertTrue(hasattr(probe, 'browser_lifecycle'), 'executable owned browser lifecycle missing')
        self._host_fixture()

    def test_owned_lifecycle_faults_cleanup_and_never_import_after_denial(self):
        for fault in ('stage', 'create', 'inspect', 'image', 'start', 'probe', 'probe-timeout', 'driver', 'cleanup'):
            with self.subTest(fault=fault):
                self._host_fixture(fault)

    def test_browser_command_is_fully_wired_but_requires_review_and_explicit_flag(self):
        with patch.object(probe, 'browser_lifecycle', return_value=2) as lifecycle, \
                patch.object(probe, 'REVIEWED_BROWSER', False), \
                patch.object(probe, '__file__', '/clone/web/arena-workbench/tests/e2e/functional-v7/ui_storage_probe.py'):
            self.assertEqual(probe.main(['--browser', '--allow-storage-browser']), 2)
            lifecycle.assert_not_called()
            with patch.object(probe, 'REVIEWED_BROWSER', True):
                self.assertEqual(probe.main(['--browser']), 2)
                lifecycle.assert_not_called()
                self.assertEqual(probe.main(['--browser', '--allow-storage-browser']), 2)
                lifecycle.assert_called_once()
                self.assertEqual(lifecycle.call_args.args[2], probe.STOPPED_FRONTEND)

    def test_fixture_explicit_css_and_build_exact_output_contract(self):
        fixture = probe.capture_fixture(Path(probe.__file__).parent)
        self.assertIn(b"import '../../../src/environment-library.css';", fixture['ui-storage-fixture.tsx'])
        driver = fixture['ui-storage-browser.mjs']
        self.assertIn(b"cssFileName: 'fixture'", driver)
        self.assertIn(b"entryFileNames: 'fixture.js'", driver)
        self.assertIn(b"assetFileNames: 'fixture.[ext]'", driver)
        self.assertIn(b"configFile: false", driver)

    def test_strict_checker_validates_partial_consistency_but_never_acceptance(self):
        self.assertTrue(hasattr(probe, 'check_storage_proof'), 'strict standalone checker missing')
        def verify(output, proof):
            self._seal_checker_fixture(output, proof)
            self.assertEqual(probe.check_storage_proof(output, require_complete=False)['status'], 'PARTIAL')
            with self.assertRaisesRegex(AssertionError, 'native cases incomplete'):
                probe.check_storage_proof(output)
        self._host_fixture(verify=verify)

    def test_checker_resealed_semantic_tampering_is_rejected(self):
        import copy
        import json
        mutations = [
            ('cleanup', lambda p, d: p.update(remaining_owned=None), 'cleanup unknown'),
            ('listing', lambda p, d: p['cleanup_verification'].update(label_ids=['c' * 64]), 'cleanup listings'),
            ('boolean network', lambda p, d: d['network'].update(overflow=0), 'errors/network'),
            ('exit', lambda p, d: p['executions'][0].update(exit_code=7), 'preflight failed'),
            ('capture limit', lambda p, d: p['executions'][0].update(capture_limit_bytes=1), 'exec capture budget'),
            ('capture incomplete', lambda p, d: p['executions'][0].update(capture_status='overflow'), 'exec capture completion'),
            ('client reap', lambda p, d: p['executions'][0].update(client_cleanup_verified=False), 'exec capture completion'),
            ('client boolean', lambda p, d: p['executions'][0].update(client_cleanup_verified=1), 'exec capture completion'),
            ('argv', lambda p, d: p['executions'][0]['argv'].insert(9, 'NODE_OPTIONS=--require=/tmp/payload'), 'sanitized exec'),
            ('image', lambda p, d: p['containers'][0].update(image='sha256:' + 'f' * 64), 'inspected identity'),
            ('source binding', lambda p, d: p['executions'][0].update(source_manifest_sha256='0' * 64), 'source/dependency binding'),
            ('readonly', lambda p, d: p['containers'][0]['mounts'][0].update(RW=True), 'mount readonly'),
            ('role', lambda p, d: p['candidates'].append('unexpected'), 'owned roles'),
            ('phase', lambda p, d: d['phases'].reverse(), 'driver phases'),
            ('overflow', lambda p, d: d['network'].update(overflow=True), 'errors/network'),
            ('observer', lambda p, d: d['result']['observations'][0].update(settledBy='request.onsuccess'), 'durable completion'),
            ('claim', lambda p, d: (p['required_cases'].update({name: 'observed' for name in probe.REQUIRED_CASES}),
                                   d['required_cases'].update(p['required_cases'])), 'unsupported native case'),
        ]
        def verify(output, proof):
            self._seal_checker_fixture(output, proof)
            original = copy.deepcopy(proof)
            driver_path = output / 'evidence/storage-browser.json'
            baseline = json.loads(driver_path.read_text())
            for name, mutate, message in mutations:
                with self.subTest(tamper=name):
                    current, driver = copy.deepcopy(original), copy.deepcopy(baseline)
                    mutate(current, driver)
                    driver_path.write_text(json.dumps(driver)); self._reseal(output, current)
                    with self.assertRaisesRegex(AssertionError, message):
                        probe.check_storage_proof(output, require_complete=False)
            current, driver = copy.deepcopy(original), copy.deepcopy(baseline)
            for observation in driver['result']['observations']:
                record = json.loads(observation['raw']); record['preferences']['pins'] = []
                observation['raw'] = json.dumps(record)
            driver_path.write_text(json.dumps(driver)); self._reseal(output, current)
            with self.assertRaisesRegex(AssertionError, 'exact expected durable pins'):
                probe.check_storage_proof(output, require_complete=False)
            current = copy.deepcopy(original); driver_path.write_text(json.dumps(baseline))
            for field in ('discovery', 'frontend_dependency_after'):
                current[field]['frontend_dependency_origin']['Mounts'][1]['Name'] = 'substituted_deps'
            self._reseal(output, current)
            with self.assertRaisesRegex(AssertionError, 'origin mount binding'):
                probe.check_storage_proof(output, require_complete=False)
        self._host_fixture(verify=verify)

    def test_bounded_capture_real_pipes_limit_timeout_and_cleanup(self):
        import subprocess
        self.assertTrue(hasattr(probe, 'capture_exec'), 'bounded streaming capture helper missing')

        for mode in ('complete', 'overflow-stdout', 'overflow-stderr', 'timeout', 'interrupt', 'read-error', 'cleanup-error'):
            with self.subTest(mode=mode):
                overflow = mode.startswith('overflow')
                out, err = (b'\xff' * 64, b'e' * 64)
                if overflow:
                    out, err = (b'x' * 4096, b'') if mode.endswith('stdout') else (b'', b'e' * 4096)
                process = PipeProcess(out, err, hold=mode in ('timeout', 'cleanup-error'),
                                      kill_error=mode == 'cleanup-error', wait_error=mode == 'cleanup-error')
                try:
                    from contextlib import ExitStack
                    with ExitStack() as stack:
                        spawn = stack.enter_context(patch.object(subprocess, 'Popen', return_value=process))
                        stack.enter_context(patch.object(probe, 'MAX_EXEC_CAPTURE_BYTES', 128))
                        if mode == 'interrupt':
                            stack.enter_context(patch('selectors.EpollSelector.select', side_effect=KeyboardInterrupt('private signal')))
                        if mode == 'read-error':
                            stack.enter_context(patch('os.read', side_effect=OSError('private read error')))
                        if mode == 'complete':
                            result = probe.capture_exec(['synthetic-no-exec'], timeout=1)
                            self.assertEqual((result.returncode, result.stdout, result.stderr), (2, out, err))
                            self.assertEqual(process.kills, 0)
                        else:
                            with self.assertRaises(probe.CaptureFailure) as caught:
                                probe.capture_exec(['synthetic-no-exec'], timeout=0.02)
                            error = caught.exception
                            self.assertNotIn('private', str(error))
                            self.assertLessEqual(len(error.stdout) + len(error.stderr), 128)
                            self.assertEqual(error.reason, 'overflow' if overflow else
                                             'timeout' if mode in ('timeout', 'cleanup-error') else
                                             'interrupted' if mode == 'interrupt' else 'capture-error')
                            self.assertEqual(error.client_cleaned, mode != 'cleanup-error')
                            if overflow:
                                self.assertEqual(len(error.stdout) + len(error.stderr), 128)
                            self.assertEqual(process.kills, 1)
                        spawn.assert_called_once_with(['synthetic-no-exec'], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, close_fds=True)
                        self.assertGreaterEqual(process.waits, 1)
                        self.assertTrue(process.stdout.closed and process.stderr.closed)
                finally:
                    process.close()
        with patch.object(subprocess, 'Popen', side_effect=OSError('private spawn error')):
            with self.assertRaises(probe.CaptureFailure) as caught:
                probe.capture_exec(['synthetic-no-exec'], timeout=1)
            self.assertEqual(str(caught.exception), 'spawn-error')
            self.assertEqual((caught.exception.stdout, caught.exception.stderr), (b'', b''))
            self.assertFalse(caught.exception.client_cleaned, 'constructor failure is not a reap witness')

    def test_checker_resealed_aggregate_matches_loader_inclusive_budget(self):
        import hashlib
        import json
        def verify(output, proof):
            self._seal_checker_fixture(output, proof)
            driver_path = output / 'evidence/storage-browser.json'
            driver = json.loads(driver_path.read_text())
            sizes = {'fixture.html': 1, 'fixture.js': 4 * 1024 * 1024, 'fixture.css': 4 * 1024 * 1024 - 1}
            for extra in (0, 1):
                for name, size in sizes.items():
                    raw = b'x' * (size + (extra if name == 'fixture.css' else 0))
                    (output / 'evidence/dist' / name).write_bytes(raw)
                    driver['fixture_sha256'][name] = hashlib.sha256(raw).hexdigest()
                driver_path.write_text(json.dumps(driver)); self._reseal(output, proof)
                if not extra:
                    self.assertEqual(probe.check_storage_proof(output, require_complete=False)['status'], 'PARTIAL')
                else:
                    with self.assertRaisesRegex(AssertionError, 'aggregate fixture budget'):
                        probe.check_storage_proof(output, require_complete=False)
        self._host_fixture(verify=verify)

    def test_checker_resealed_combined_capture_budget_is_inclusive(self):
        def verify(output, proof):
            self._seal_checker_fixture(output, proof)
            row = proof['executions'][1]
            for extra in (0, 1):
                (output / row['stdout']).chmod(0o600)
                (output / row['stderr']).chmod(0o600)
                (output / row['stdout']).write_bytes(b'o' * (probe.MAX_EXEC_CAPTURE_BYTES // 2))
                (output / row['stderr']).write_bytes(b'e' * (probe.MAX_EXEC_CAPTURE_BYTES // 2 + extra))
                self._reseal(output, proof)
                if not extra:
                    self.assertEqual(probe.check_storage_proof(output, require_complete=False)['status'], 'PARTIAL')
                else:
                    with self.assertRaisesRegex(AssertionError, 'exec capture budget'):
                        probe.check_storage_proof(output, require_complete=False)
        self._host_fixture(verify=verify)

    def test_checker_rejects_child_and_host_capture_symlinks(self):
        def verify(output, proof):
            self._seal_checker_fixture(output, proof)
            for name in ('evidence/dist/fixture.js', 'host-capture/storage-driver.stdout'):
                with self.subTest(name=name):
                    leaf = output / name
                    raw = leaf.read_bytes()
                    target = output.parent / 'synthetic-copy'
                    target.write_bytes(raw)
                    leaf.unlink(); leaf.symlink_to(target)
                    try:
                        with self.assertRaisesRegex(OSError, 'singly-linked regular'):
                            probe.check_storage_proof(output, require_complete=False)
                        self.assertEqual(target.read_bytes(), raw)
                    finally:
                        leaf.unlink(); leaf.write_bytes(raw)
        self._host_fixture(verify=verify)

    def test_host_capture_never_writes_child_symlinks_in_any_outcome(self):
        for fault in ('symlink-success', 'symlink-error', 'symlink-timeout', 'symlink-cleanup'):
            with self.subTest(fault=fault):
                self._host_fixture(fault)

    def test_host_stream_budget_failure_is_static_nonzero_and_cleans_owned(self):
        for fault in ('capture-overflow', 'capture-timeout', 'capture-cleanup'):
            with self.subTest(fault=fault), patch.object(probe, 'MAX_EXEC_CAPTURE_BYTES', 512):
                def verify(output, proof):
                    self.assertEqual(len(proof['executions']), 2, 'bounded driver invocation never reached')
                    row = proof['executions'][-1]
                    self.assertEqual(row['exit_code'], None)
                    self.assertEqual(row.get('capture_status'), 'overflow' if fault == 'capture-overflow' else 'timeout')
                    self.assertEqual(row['client_cleanup_verified'], fault != 'capture-cleanup')
                    self.assertEqual(row['error'], 'CaptureFailure: ' + row['capture_status'])
                    self.assertLessEqual(sum((output / row[key]).stat().st_size for key in ('stdout', 'stderr')), 512)
                    self.assertEqual(proof['cleanup_verified'], True)
                    self.assertEqual(proof['remaining_owned'], [])
                self._host_fixture(fault, verify=verify)

    def test_host_capture_collision_never_rolls_back_or_follows_link(self):
        def verify(output, proof):
            self.assertEqual((output / 'host-capture/storage-driver.stdout').read_bytes(), b'synthetic driver')
            self.assertTrue((output / 'host-capture/storage-driver.stderr').is_symlink())
            self.assertTrue(proof['evidence_errors'])
        self._host_fixture('capture-collision', verify=verify)

    def test_host_rejects_driver_self_reported_full_acceptance(self):
        self._host_fixture('false-passed')

    def test_standalone_checker_cli_cannot_turn_partial_into_zero_exit(self):
        def verify(output, proof):
            self._seal_checker_fixture(output, proof)
            self.assertEqual(probe.main(['--check', str(output)]), 1)
            self.assertEqual(probe.main(['--check-partial', str(output)]), 2)
        self._host_fixture(verify=verify)

    def test_fixture_freezes_host_preflight_and_checker_sources(self):
        self.assertTrue({'ui_storage_probe.py', 'run.py', 'confined_io.py', 'frontend_checks.py', 'check_proof.py'} <= set(probe.FIXTURE_FILES))

    def _seal_checker_fixture(self, output, proof):
        """Explicit synthetic producer bundle; cannot establish execution authenticity."""
        import json
        import hashlib
        from frontend_checks import PROBE
        h = lambda data: hashlib.sha256(data).hexdigest()
        for name in ('src/environment-library.tsx', 'src/environment-library.css', 'src/environment-library-contract.ts',
                     'src/library-preferences.ts', 'src/library-preferences-native.ts', 'package.json', 'package-lock.json',
                     *('tests/e2e/functional-v7/' + name for name in probe.FIXTURE_FILES)):
            path = output / 'source' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('// synthetic frozen source: ' + name)
            proof['source_sha256'][name] = h(path.read_bytes())
        (output / 'source-manifest.json').write_text(json.dumps(proof['source_sha256'], sort_keys=True, indent=2))
        manifest_hash = h((output / 'source-manifest.json').read_bytes())
        for execution in proof['executions']:
            execution['source_manifest_sha256'] = manifest_hash
        pins = [{'id': 'editor-revision:' + digit * 32, 'kind': 'editor_revision', 'revision_id': digit * 32,
                 'source_hash': digit * 64, 'canonical_hash': 'a' * 64} for digit in ('1', '2')]
        observation = {'state': 'record', 'settledBy': 'transaction.oncomplete', 'raw': json.dumps({
            'schemaVersion': 1, 'revision': 4, 'preferences': {'version': 1, 'pins': pins, 'recents': pins}})}
        dist = output / 'evidence/dist'; dist.mkdir()
        for name in ('fixture.html', 'fixture.js', 'fixture.css'):
            (dist / name).write_text('synthetic fixture asset: ' + name)
        driver = {'schema_version': 1, 'profile': 'native-ui-storage-probe-v1', 'status': 'PARTIAL',
                  'real_api_evidence': False, 'errors': [], 'rejected': [], 'network': {'overflow': False},
                  'cleanup_verified': True, 'browser_version': 'synthetic-not-a-browser-run',
                  'required_cases': {name: 'NOT-RUN' for name in probe.REQUIRED_CASES},
                  'phases': [{'name': name, 'status': 'completed'} for name in
                             ('preflight', 'imports', 'build', 'load', 'launch', 'context', 'routes', 'observe')],
                  'fixture_sha256': {name.name: h(name.read_bytes()) for name in dist.iterdir()},
                  'result': {'scope': 'synthetic parent-prop fixture; actual native engine; no API/source verification',
                             'schedule': 'concurrent clicks; transaction overlap NOT witnessed',
                             'observations': [observation, observation], 'legacyBefore': None, 'legacyAfter': None}}
        (output / 'evidence/storage-browser.json').write_text(json.dumps(driver))
        (output / 'evidence/preimport-storage-browser.json').write_text(json.dumps({
            'status': 'passed', 'uid': 1000, 'egress_denied': True, 'code': 'ENETUNREACH', 'before_repository_imports': True}))
        self._reseal(output, proof)

    def _reseal(self, output, proof):
        import json
        import hashlib
        from run import hash_evidence
        proof['artifacts'] = {}
        errors = []; hash_evidence(output, proof['artifacts'], errors)
        self.assertEqual(errors, [])
        for execution in proof['executions']:
            for key in ('stdout', 'stderr'):
                name = execution[key]
                proof['artifacts'][name] = hashlib.sha256((output / name).read_bytes()).hexdigest()
        proof['artifacts']['source-manifest.json'] = hashlib.sha256((output / 'source-manifest.json').read_bytes()).hexdigest()
        (output / 'ownership.json').write_text(json.dumps(proof))
        proof['artifacts']['ownership.json'] = hashlib.sha256((output / 'ownership.json').read_bytes()).hexdigest()
        (output / 'run-proof.json').write_text(json.dumps(proof))

    def _host_fixture(self, fault=None, verify=None):
        """Synthetic daemon/exec callbacks; exercises real OwnedRun, never Docker."""
        import json
        import hashlib
        import run
        import subprocess
        import frontend_checks
        from contextlib import ExitStack
        original_owned = run.OwnedRun
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory); output = root / 'output'; output.mkdir()
            sentinel = root / 'synthetic-host-target'
            sentinel.write_bytes(b'untouched synthetic target')
            records, calls = [], []
            cid = 'c' * 64
            mounted = []; removed = False
            def daemon(*args):
                nonlocal removed
                calls.append(args)
                if args[0] == 'create':
                    owned = records[0]
                    import os
                    capture_stat = (output / 'host-capture').stat()
                    self.assertEqual(capture_stat.st_mode & 0o777, 0o700)
                    self.assertEqual(capture_stat.st_uid, os.getuid())
                    saved = json.loads((output / 'ownership.json').read_text())
                    self.assertEqual(saved['candidates'], [owned.token + '-storage'])
                    for flag in ('--network=none', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges'):
                        self.assertIn(flag, args)
                    for index, arg in enumerate(args):
                        if arg == '--mount':
                            parts = dict(piece.split('=', 1) if '=' in piece else (piece, True) for piece in args[index + 1].split(','))
                            mounted.append({'Type': parts['type'], 'Source': parts['src'], 'Name': parts['src'] if parts['type'] == 'volume' else '',
                                            'Destination': parts['dst'], 'RW': not parts.get('readonly', False)})
                    if fault == 'create': raise TimeoutError('create ACK unknown')
                    return cid
                if args[0] == 'inspect':
                    owned = records[0]
                    if args[2] == run.IDENTITY_FORMAT:
                        return json.dumps({'Id': cid, 'Name': '/' + owned.token + '-storage', 'Label': owned.token})
                    self.assertEqual(json.loads((output / 'ownership.json').read_text())['created_ids'], {owned.token + '-storage': cid})
                    host = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'CapDrop': ['ALL'], 'CapAdd': [],
                            'SecurityOpt': ['no-new-privileges'], 'DeviceRequests': [], 'Devices': [], 'Privileged': False,
                            'Binds': [], 'VolumesFrom': [], 'PortBindings': {}, 'PidMode': '', 'IpcMode': 'private', 'UsernsMode': '',
                            'PidsLimit': 256, 'Memory': 4294967296, 'Tmpfs': {'/tmp': 'rw,nosuid,nodev', '/private': 'rw,nosuid,nodev'}}
                    if fault == 'inspect': host['NetworkMode'] = 'host'
                    return json.dumps({'Id': cid, 'Name': '/' + owned.token + '-storage',
                        'Image': 'sha256:' + 'f' * 64 if fault == 'image' else probe.PLAYWRIGHT_ID,
                        'Config': {'User': '1000:1000', 'Labels': {run.LABEL: owned.token}}, 'HostConfig': host, 'Mounts': mounted})
                if args[0] == 'start':
                    self.assertTrue(records[0].proof['verified_isolation'][records[0].token + '-storage'])
                    if fault == 'start': raise RuntimeError('start fault')
                    return cid
                if args[0] == 'ps':
                    if fault in ('cleanup', 'symlink-cleanup'): raise TimeoutError('unknown cleanup')
                    return '' if removed or not records[0].candidates else cid
                if args[0] == 'rm': removed = True; return ''
                if args[0] == 'logs': return 'synthetic keeper log'
                raise AssertionError(args)
            def owned(out, token):
                value = original_owned(out, token, daemon); records.append(value); return value
            discovery = {'host_root': str(root), 'deps': 'installed_deps', 'frontend_dependency_origin': {
                'Id': probe.STOPPED_FRONTEND, 'Image': probe.PLAYWRIGHT_ID, 'Status': 'exited', 'Running': False,
                'Mounts': [{'Type': 'bind', 'Source': str(root) + '/web/arena-workbench', 'Destination': '/app'},
                           {'Type': 'volume', 'Name': 'installed_deps', 'Destination': '/app/node_modules'}]}}
            def stage(frontend, destination):
                if fault == 'stage': raise OSError('staging fault')
                destination.mkdir(); (destination / 'node_modules').mkdir()
                (destination / 'inert.ts').write_bytes(b'// synthetic')
                return {'inert.ts': hashlib.sha256(b'// synthetic').hexdigest()}
            def execute(argv, **kwargs):
                calls.append(tuple(argv))
                self.assertEqual(argv[:6], ['docker', 'exec', '--user', '1000:1000', '-w', '/app'])
                self.assertEqual(argv[6], cid)
                self.assertEqual(argv[7:9], ['/usr/bin/env', '-i'])
                self.assertFalse(any('NODE_OPTIONS=' in arg for arg in argv))
                if argv[-1] == frontend_checks.PROBE:
                    if fault == 'probe-timeout': raise subprocess.TimeoutExpired(argv, 45, b'partial scan', b'fault')
                    value = {'status': 'passed', 'uid': 1000, 'egress_denied': True, 'before_repository_imports': True,
                             'code': 'ENETUNREACH', 'readonly_source_root_deps': True, 'no_new_privileges': True,
                             'gpu_devices': [], 'dependency_entries': 12,
                             'dependency_trust': 'trusted mutable installed frontend volume; not immutable provenance'}
                    (output / 'evidence/preimport-frontend.json').write_text(json.dumps(value))
                    return subprocess.CompletedProcess(argv, 7 if fault == 'probe' else 0, json.dumps(value).encode(), b'')
                self.assertTrue((output / 'evidence/preimport-frontend.json').exists())
                self.assertEqual(records[0].proof['executions'][0]['exit_code'], 0)
                if fault == 'capture-collision':
                    # Synthetic host-side interference, NOT container authority.
                    (output / 'host-capture/storage-driver.stderr').symlink_to(sentinel)
                if fault and fault.startswith('symlink-'):
                    for suffix in ('stdout', 'stderr'):
                        (output / ('evidence/storage-driver.' + suffix)).symlink_to(sentinel)
                    if fault == 'symlink-error': raise OSError('synthetic exec error')
                    if fault == 'symlink-timeout': raise subprocess.TimeoutExpired(argv, 240, b'partial output', b'partial error')
                value = {'status': 'passed' if fault == 'false-passed' else 'PARTIAL', 'errors': [], 'cleanup_verified': True}
                (output / 'evidence/storage-browser.json').write_text(json.dumps(value))
                return subprocess.CompletedProcess(argv, 0 if fault == 'false-passed' else 1 if fault == 'driver' else 2,
                    b'x' * 513 if fault == 'capture-overflow' else b'synthetic driver', b'')
            processes = []
            def spawn(argv, **kwargs):
                hold = fault in ('capture-timeout', 'capture-cleanup') and argv[-1] == probe.BROWSER_ENTRY
                try:
                    result = execute(argv)
                except subprocess.TimeoutExpired as error:
                    result = subprocess.CompletedProcess(argv, 1, error.stdout, error.stderr)
                    hold = True
                process = PipeProcess(result.stdout, result.stderr, hold=hold,
                    kill_error=fault == 'capture-cleanup' and hold, wait_error=fault == 'capture-cleanup' and hold,
                    exit_code=result.returncode)
                processes.append(process)
                stack.callback(process.close)
                return process
            stack.enter_context(patch.object(run, 'OwnedRun', side_effect=owned))
            stack.enter_context(patch.object(run, 'docker', side_effect=daemon))
            stack.enter_context(patch.object(run, 'discover_frontend', return_value=discovery))
            stack.enter_context(patch.object(run, 'image_metadata', return_value={'Id': probe.PLAYWRIGHT_ID, 'Volumes': None}))
            stack.enter_context(patch.object(probe, 'stage_browser', side_effect=stage))
            stack.enter_context(patch('os.chown'))
            original_capture = probe.capture_exec
            timeout_faults = ('probe-timeout', 'symlink-timeout', 'capture-timeout', 'capture-cleanup')
            stack.enter_context(patch.object(probe, 'capture_exec', side_effect=lambda argv, timeout:
                original_capture(argv, min(timeout, 0.1 if fault in timeout_faults else 2))))
            stack.enter_context(patch.object(subprocess, 'Popen', side_effect=spawn))
            stack.enter_context(patch.object(subprocess, 'run', side_effect=AssertionError('unbounded subprocess.run forbidden')))
            code = probe.browser_lifecycle(root, output, probe.STOPPED_FRONTEND)
            proof = json.loads((output / 'run-proof.json').read_text())
            for process in processes:
                self.assertTrue(process.stdout.closed and process.stderr.closed)
                self.assertGreaterEqual(process.waits, 1)
            self.assertEqual(sentinel.read_bytes(), b'untouched synthetic target')
            if fault and fault.startswith('symlink-'):
                self.assertTrue((output / 'evidence/storage-driver.stdout').is_symlink(), 'synthetic attack never reached')
                self.assertEqual((output / 'host-capture/storage-driver.stdout').read_bytes(),
                    b'partial output' if fault == 'symlink-timeout' else b'' if fault == 'symlink-error' else b'synthetic driver')
            for execution in proof['executions']:
                for suffix in ('stdout', 'stderr'):
                    self.assertEqual(execution[suffix], 'host-capture/' + execution['role'] + '.' + suffix)
            self.assertFalse(any(row['Source'] == str(output / 'host-capture') for row in mounted))
            self.assertEqual(code, 2 if fault is None else 1)
            self.assertEqual(proof['status'], 'PARTIAL' if fault is None else 'failed')
            self.assertEqual(proof['cleanup_verified'], fault not in ('cleanup', 'symlink-cleanup'))
            self.assertEqual(proof['remaining_owned'], None if fault in ('cleanup', 'symlink-cleanup') else [])
            self.assertEqual(proof['artifacts']['ownership.json'], hashlib.sha256((output / 'ownership.json').read_bytes()).hexdigest())
            if fault in ('create', 'stage', 'image', 'inspect', 'start', 'probe', 'probe-timeout'):
                self.assertFalse(any(call[-1] == probe.BROWSER_ENTRY for call in calls))
            if fault is None:
                self.assertEqual([row['exit_code'] for row in proof['executions']], [0, 2])
                self.assertEqual(proof['executions'][0]['argv'][-1], frontend_checks.PROBE)
                self.assertEqual(proof['executions'][0]['container_id'], cid)
                self.assertEqual(proof['executions'][0]['image_id'], probe.PLAYWRIGHT_ID)
                self.assertEqual(proof['executions'][0]['source_manifest_sha256'], proof['artifacts']['source-manifest.json'])
            if verify is not None:
                verify(output, proof)

    def test_browser_gate_denies_before_discovery_even_with_flags(self):
        with patch.object(probe, 'REVIEWED_BROWSER', False), \
                patch('run.discover_frontend', side_effect=AssertionError('must not discover')):
            for argv in ([], ['--browser'], ['--browser', '--allow-storage-browser']):
                with self.subTest(argv=argv):
                    self.assertEqual(probe.main(argv), 2)

    def test_fixture_capture_fixed_allowlist_and_link_denial(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            for name in probe.FIXTURE_FILES:
                (source / name).write_text(name)
            data = probe.capture_fixture(source)
            self.assertEqual(set(data), set(probe.FIXTURE_FILES))
            (source / '.env').write_text('not included')
            self.assertEqual(probe.capture_fixture(source), data)
            target = source / probe.FIXTURE_FILES[0]
            target.unlink()
            target.symlink_to(source / '.env')
            with self.assertRaisesRegex(OSError, 'singly-linked regular'):
                probe.capture_fixture(source)

    def test_fixture_total_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in probe.FIXTURE_FILES:
                (root / name).write_bytes(b'x' * (probe.MAX_FIXTURE_BYTES // len(probe.FIXTURE_FILES) + 1))
            with self.assertRaisesRegex(AssertionError, 'fixture aggregate'):
                probe.capture_fixture(root)

    def test_real_frontend_capture_plus_fixed_fixture_staging(self):
        import hashlib
        import json
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frontend = root / 'frontend'
            (frontend / 'src').mkdir(parents=True)
            fixture = frontend / 'tests/e2e/functional-v7'
            fixture.mkdir(parents=True)
            (frontend / 'package.json').write_text(json.dumps({'scripts': {
                'typecheck': 'tsc --noEmit', 'build': 'tsc --noEmit && vite build'}}))
            for name in ('package-lock.json', 'tsconfig.json'):
                (frontend / name).write_text('{}')
            (frontend / 'index.html').write_text('<html></html>')
            (frontend / 'src/only.ts').write_text('export const inert = true;')
            for name in probe.FIXTURE_FILES:
                (fixture / name).write_text('inert fixture bytes: ' + name)
            target = root / 'staged'
            manifest = probe.stage_browser(frontend, target)
            self.assertTrue((target / 'node_modules').is_dir())
            self.assertEqual(len(manifest), 5 + len(probe.FIXTURE_FILES))
            for name, digest in manifest.items():
                self.assertEqual(hashlib.sha256((target / name).read_bytes()).hexdigest(), digest)
            self.assertNotIn('.env', manifest)

    def test_no_arbitrary_fixture_or_container_selector(self):
        with self.assertRaises(SystemExit):
            probe.main(['--safeunits', '--fixture', '../../secret'])
        with self.assertRaisesRegex(AssertionError, 'exact approved stopped'):
            probe.main(['--safeunits', '--frontend-dependency-container', '964ddf2'])


if __name__ == '__main__':
    unittest.main()
