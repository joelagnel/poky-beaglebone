# ex:ts=4:sw=4:sts=4:et
# -*- tab-width: 4; c-basic-offset: 4; indent-tabs-mode: nil -*-
"""
 AbstractSyntaxTree classes for the Bitbake language
"""

# Copyright (C) 2003, 2004 Chris Larson
# Copyright (C) 2003, 2004 Phil Blundell
# Copyright (C) 2009 Holger Hans Peter Freyther
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

from __future__ import absolute_import
from future_builtins import filter
import re
import string
import logging
import bb
import itertools
from bb import methodpool
from bb.parse import logger

_bbversions_re = re.compile(r"\[(?P<from>[0-9]+)-(?P<to>[0-9]+)\]")

class StatementGroup(list):
    def eval(self, data):
        for statement in self:
            statement.eval(data)

class AstNode(object):
    def __init__(self, filename, lineno):
        self.filename = filename
        self.lineno = lineno

class IncludeNode(AstNode):
    def __init__(self, filename, lineno, what_file, force):
        AstNode.__init__(self, filename, lineno)
        self.what_file = what_file
        self.force = force

    def eval(self, data):
        """
        Include the file and evaluate the statements
        """
        s = data.expand(self.what_file)
        logger.debug(2, "CONF %s:%s: including %s", self.filename, self.lineno, s)

        # TODO: Cache those includes... maybe not here though
        if self.force:
            bb.parse.ConfHandler.include(self.filename, s, self.lineno, data, "include required")
        else:
            bb.parse.ConfHandler.include(self.filename, s, self.lineno, data, False)

class ExportNode(AstNode):
    def __init__(self, filename, lineno, var):
        AstNode.__init__(self, filename, lineno)
        self.var = var

    def eval(self, data):
        data.setVarFlag(self.var, "export", 1, op = 'exported')

class DataNode(AstNode):
    """
    Various data related updates. For the sake of sanity
    we have one class doing all this. This means that all
    this need to be re-evaluated... we might be able to do
    that faster with multiple classes.
    """
    def __init__(self, filename, lineno, groupd):
        AstNode.__init__(self, filename, lineno)
        self.groupd = groupd

    def getFunc(self, key, data):
        if 'flag' in self.groupd and self.groupd['flag'] != None:
            return data.getVarFlag(key, self.groupd['flag'], noweakdefault=True)
        else:
            return data.getVar(key, noweakdefault=True)

    def eval(self, data):
        groupd = self.groupd
        key = groupd["var"]
        loginfo = {
            'variable': key,
            'file': self.filename,
            'line': self.lineno,
        }
        if "exp" in groupd and groupd["exp"] != None:
            data.setVarFlag(key, "export", 1, op = 'exported', **loginfo)

        op = "set"
        if "ques" in groupd and groupd["ques"] != None:
            val = self.getFunc(key, data)
            op = "set?"
            if val == None:
                val = groupd["value"]
        elif "colon" in groupd and groupd["colon"] != None:
            e = data.createCopy()
            bb.data.update_data(e)
            op = "immediate"
            val = e.expand(groupd["value"], key + "[:=]")
        elif "append" in groupd and groupd["append"] != None:
            op = "append"
            val = "%s %s" % ((self.getFunc(key, data) or ""), groupd["value"])
        elif "prepend" in groupd and groupd["prepend"] != None:
            op = "prepend"
            val = "%s %s" % (groupd["value"], (self.getFunc(key, data) or ""))
        elif "postdot" in groupd and groupd["postdot"] != None:
            op = "postdot"
            val = "%s%s" % ((self.getFunc(key, data) or ""), groupd["value"])
        elif "predot" in groupd and groupd["predot"] != None:
            op = "predot"
            val = "%s%s" % (groupd["value"], (self.getFunc(key, data) or ""))
        else:
            val = groupd["value"]

        flag = None
        if 'flag' in groupd and groupd['flag'] != None:
            flag = groupd['flag']
        elif groupd["lazyques"]:
            flag = "defaultval"

        loginfo['op'] = op
        loginfo['detail'] = groupd["value"]

        if flag:
            data.setVarFlag(key, flag, val, **loginfo)
        else:
            data.setVar(key, val, **loginfo)

class MethodNode(AstNode):
    tr_tbl = string.maketrans('/.+-@%', '______')

    def __init__(self, filename, lineno, func_name, body):
        AstNode.__init__(self, filename, lineno)
        self.func_name = func_name
        self.body = body

    def eval(self, data):
        text = '\n'.join(self.body)
        if self.func_name == "__anonymous":
            funcname = ("__anon_%s_%s" % (self.lineno, self.filename.translate(MethodNode.tr_tbl)))
            text = "def %s(d):\n" % (funcname) + text
            bb.methodpool.insert_method(funcname, text, self.filename)
            anonfuncs = data.getVar('__BBANONFUNCS') or []
            anonfuncs.append(funcname)
            data.setVar('__BBANONFUNCS', anonfuncs)
            data.setVar(funcname, text)
        else:
            data.setVarFlag(self.func_name, "func", 1)
            data.setVar(self.func_name, text)

class PythonMethodNode(AstNode):
    def __init__(self, filename, lineno, function, modulename, body):
        AstNode.__init__(self, filename, lineno)
        self.function = function
        self.modulename = modulename
        self.body = body

    def eval(self, data):
        # Note we will add root to parsedmethods after having parse
        # 'this' file. This means we will not parse methods from
        # bb classes twice
        text = '\n'.join(self.body)
        bb.methodpool.insert_method(self.modulename, text, self.filename)
        data.setVarFlag(self.function, "func", 1)
        data.setVarFlag(self.function, "python", 1)
        data.setVar(self.function, text)

class MethodFlagsNode(AstNode):
    def __init__(self, filename, lineno, key, m):
        AstNode.__init__(self, filename, lineno)
        self.key = key
        self.m = m

    def eval(self, data):
        if data.getVar(self.key):
            # clean up old version of this piece of metadata, as its
            # flags could cause problems
            data.setVarFlag(self.key, 'python', None)
            data.setVarFlag(self.key, 'fakeroot', None)
        if self.m.group("py") is not None:
            data.setVarFlag(self.key, "python", "1")
        else:
            data.delVarFlag(self.key, "python")
        if self.m.group("fr") is not None:
            data.setVarFlag(self.key, "fakeroot", "1")
        else:
            data.delVarFlag(self.key, "fakeroot")

class ExportFuncsNode(AstNode):
    def __init__(self, filename, lineno, fns, classname):
        AstNode.__init__(self, filename, lineno)
        self.n = fns.split()
        self.classname = classname

    def eval(self, data):

        for func in self.n:
            calledfunc = self.classname + "_" + func

            if data.getVar(func) and not data.getVarFlag(func, 'export_func'):
                continue

            if data.getVar(func):
                data.setVarFlag(func, 'python', None)
                data.setVarFlag(func, 'func', None)

            for flag in [ "func", "python" ]:
                if data.getVarFlag(calledfunc, flag):
                    data.setVarFlag(func, flag, data.getVarFlag(calledfunc, flag))
            for flag in [ "dirs" ]:
                if data.getVarFlag(func, flag):
                    data.setVarFlag(calledfunc, flag, data.getVarFlag(func, flag))

            if data.getVarFlag(calledfunc, "python"):
                data.setVar(func, "    bb.build.exec_func('" + calledfunc + "', d)\n")
            else:
                data.setVar(func, "    " + calledfunc + "\n")
            data.setVarFlag(func, 'export_func', '1')

class AddTaskNode(AstNode):
    def __init__(self, filename, lineno, func, before, after):
        AstNode.__init__(self, filename, lineno)
        self.func = func
        self.before = before
        self.after = after

    def eval(self, data):
        bb.build.addtask(self.func, self.before, self.after, data)

class DelTaskNode(AstNode):
    def __init__(self, filename, lineno, func):
        AstNode.__init__(self, filename, lineno)
        self.func = func

    def eval(self, data):
        bb.build.deltask(self.func, data)

class BBHandlerNode(AstNode):
    def __init__(self, filename, lineno, fns):
        AstNode.__init__(self, filename, lineno)
        self.hs = fns.split()

    def eval(self, data):
        bbhands = data.getVar('__BBHANDLERS') or []
        for h in self.hs:
            bbhands.append(h)
            data.setVarFlag(h, "handler", 1)
        data.setVar('__BBHANDLERS', bbhands)

class InheritNode(AstNode):
    def __init__(self, filename, lineno, classes):
        AstNode.__init__(self, filename, lineno)
        self.classes = classes

    def eval(self, data):
        bb.parse.BBHandler.inherit(self.classes, self.filename, self.lineno, data)

def handleInclude(statements, filename, lineno, m, force):
    statements.append(IncludeNode(filename, lineno, m.group(1), force))

def handleExport(statements, filename, lineno, m):
    statements.append(ExportNode(filename, lineno, m.group(1)))

def handleData(statements, filename, lineno, groupd):
    statements.append(DataNode(filename, lineno, groupd))

def handleMethod(statements, filename, lineno, func_name, body):
    statements.append(MethodNode(filename, lineno, func_name, body))

def handlePythonMethod(statements, filename, lineno, funcname, modulename, body):
    statements.append(PythonMethodNode(filename, lineno, funcname, modulename, body))

def handleMethodFlags(statements, filename, lineno, key, m):
    statements.append(MethodFlagsNode(filename, lineno, key, m))

def handleExportFuncs(statements, filename, lineno, m, classname):
    statements.append(ExportFuncsNode(filename, lineno, m.group(1), classname))

def handleAddTask(statements, filename, lineno, m):
    func = m.group("func")
    before = m.group("before")
    after = m.group("after")
    if func is None:
        return

    statements.append(AddTaskNode(filename, lineno, func, before, after))

def handleDelTask(statements, filename, lineno, m):
    func = m.group("func")
    if func is None:
        return

    statements.append(DelTaskNode(filename, lineno, func))

def handleBBHandlers(statements, filename, lineno, m):
    statements.append(BBHandlerNode(filename, lineno, m.group(1)))

def handleInherit(statements, filename, lineno, m):
    classes = m.group(1)
    statements.append(InheritNode(filename, lineno, classes))

def finalize(fn, d, variant = None):
    all_handlers = {}
    for var in d.getVar('__BBHANDLERS') or []:
        # try to add the handler
        bb.event.register(var, d.getVar(var), (d.getVarFlag(var, "eventmask", True) or "").split())

    bb.event.fire(bb.event.RecipePreFinalise(fn), d)

    bb.data.expandKeys(d)
    bb.data.update_data(d)
    code = []
    for funcname in d.getVar("__BBANONFUNCS") or []:
        code.append("%s(d)" % funcname)
    bb.utils.better_exec("\n".join(code), {"d": d})
    bb.data.update_data(d)

    tasklist = d.getVar('__BBTASKS') or []
    deltasklist = d.getVar('__BBDELTASKS') or []
    bb.build.add_tasks(tasklist, deltasklist, d)

    bb.parse.siggen.finalise(fn, d, variant)

    d.setVar('BBINCLUDED', bb.parse.get_file_depends(d))

    bb.event.fire(bb.event.RecipeParsed(fn), d)

def _create_variants(datastores, names, function, onlyfinalise):
    def create_variant(name, orig_d, arg = None):
        if onlyfinalise and name not in onlyfinalise:
            return
        new_d = bb.data.createCopy(orig_d)
        function(arg or name, new_d)
        datastores[name] = new_d

    for variant, variant_d in datastores.items():
        for name in names:
            if not variant:
                # Based on main recipe
                create_variant(name, variant_d)
            else:
                create_variant("%s-%s" % (variant, name), variant_d, name)

def _expand_versions(versions):
    def expand_one(version, start, end):
        for i in xrange(start, end + 1):
            ver = _bbversions_re.sub(str(i), version, 1)
            yield ver

    versions = iter(versions)
    while True:
        try:
            version = next(versions)
        except StopIteration:
            break

        range_ver = _bbversions_re.search(version)
        if not range_ver:
            yield version
        else:
            newversions = expand_one(version, int(range_ver.group("from")),
                                     int(range_ver.group("to")))
            versions = itertools.chain(newversions, versions)

def multi_finalize(fn, d):
    appends = (d.getVar("__BBAPPEND", True) or "").split()
    for append in appends:
        logger.debug(2, "Appending .bbappend file %s to %s", append, fn)
        bb.parse.BBHandler.handle(append, d, True)

    onlyfinalise = d.getVar("__ONLYFINALISE", False)

    safe_d = d
    d = bb.data.createCopy(safe_d)
    try:
        finalize(fn, d)
    except bb.parse.SkipPackage as e:
        d.setVar("__SKIPPED", e.args[0])
    datastores = {"": safe_d}

    versions = (d.getVar("BBVERSIONS", True) or "").split()
    if versions:
        pv = orig_pv = d.getVar("PV", True)
        baseversions = {}

        def verfunc(ver, d, pv_d = None):
            if pv_d is None:
                pv_d = d

            overrides = d.getVar("OVERRIDES", True).split(":")
            pv_d.setVar("PV", ver)
            overrides.append(ver)
            bpv = baseversions.get(ver) or orig_pv
            pv_d.setVar("BPV", bpv)
            overrides.append(bpv)
            d.setVar("OVERRIDES", ":".join(overrides))

        versions = list(_expand_versions(versions))
        for pos, version in enumerate(list(versions)):
            try:
                pv, bpv = version.split(":", 2)
            except ValueError:
                pass
            else:
                versions[pos] = pv
                baseversions[pv] = bpv

        if pv in versions and not baseversions.get(pv):
            versions.remove(pv)
        else:
            pv = versions.pop()

            # This is necessary because our existing main datastore
            # has already been finalized with the old PV, we need one
            # that's been finalized with the new PV.
            d = bb.data.createCopy(safe_d)
            verfunc(pv, d, safe_d)
            try:
                finalize(fn, d)
            except bb.parse.SkipPackage as e:
                d.setVar("__SKIPPED", e.args[0])

        _create_variants(datastores, versions, verfunc, onlyfinalise)

    extended = d.getVar("BBCLASSEXTEND", True) or ""
    if extended:
        # the following is to support bbextends with arguments, for e.g. multilib
        # an example is as follows:
        #   BBCLASSEXTEND = "multilib:lib32"
        # it will create foo-lib32, inheriting multilib.bbclass and set
        # BBEXTENDCURR to "multilib" and BBEXTENDVARIANT to "lib32"
        extendedmap = {}
        variantmap = {}

        for ext in extended.split():
            eext = ext.split(':', 2)
            if len(eext) > 1:
                extendedmap[ext] = eext[0]
                variantmap[ext] = eext[1]
            else:
                extendedmap[ext] = ext

        pn = d.getVar("PN", True)
        def extendfunc(name, d):
            if name != extendedmap[name]:
                d.setVar("BBEXTENDCURR", extendedmap[name])
                d.setVar("BBEXTENDVARIANT", variantmap[name])
            else:
                d.setVar("PN", "%s-%s" % (pn, name))
            bb.parse.BBHandler.inherit(extendedmap[name], fn, 0, d)

        safe_d.setVar("BBCLASSEXTEND", extended)
        _create_variants(datastores, extendedmap.keys(), extendfunc, onlyfinalise)

    for variant, variant_d in datastores.iteritems():
        if variant:
            try:
                if not onlyfinalise or variant in onlyfinalise:
                    finalize(fn, variant_d, variant)
            except bb.parse.SkipPackage as e:
                variant_d.setVar("__SKIPPED", e.args[0])

    if len(datastores) > 1:
        variants = filter(None, datastores.iterkeys())
        safe_d.setVar("__VARIANTS", " ".join(variants))

    datastores[""] = d
    return datastores
