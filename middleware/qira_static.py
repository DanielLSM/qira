#!/usr/bin/env python2.7
from qira_base import *
import qira_config
from qira_webserver import socket_method, socketio, app
from flask import request
from flask.ext.socketio import SocketIO, emit
import os
import sys
import json

if qira_config.WITH_IDA:
  # this import requires python32
  from static import ida

if qira_config.WITH_RADARE:
  #sys.path.append(qira_config.BASEDIR+"/radare2/radare2-bindings/ctypes")
  #import r_bin
  from r2.r_core import RCore

# should namespace be changed to static?

# type -- ["int", "float", "string", "pointer"] 
# len -- bytes that go with this one
# name -- name of this address
# comment -- comment on this address
# instruction -- string of this instruction
# flow -- see eda-3 docs
# xrefs -- things that point to this
# code -- 'foo.c:38', from DWARF or hexrays
# semantics -- basic block start, is call, is ret, read regs, write regs
# funclength -- this is the start of a function with length
# scope -- first address in function
# flags -- copied from ida

# coming soon
# capinstruction -- instruction data generated by capstone
# bap -- semantics taken from BAP

# handle functions outside this
#   function stack frames
#   decompilation


# *** NEWER STATIC FUNCTIONS USE IDA AS STATIC BACKEND ***

def get_static_bytes(addr, llen, numlist=False):
  try:
    ret = elf_dat[addr-load_addr:addr-load_addr+program.tags[addr]['len']]
    if numlist:
      return map(ord, list(ret))
    else:
      return ret
  except:
    return None

# input is a list of addresses, output is a dictionary names if they exist
@socketio.on('getnames', namespace='/qira')
@socket_method
def getnames(addrs):
  ret = {}
  for i in addrs:
    i = fhex(i)
    # this is slow
    if False and qira_config.WITH_IDA:
      name = ida.get_name(i)
      #print i, name
      if name != None:
        ret[ghex(i)] = name
    else:
      if 'name' in program.tags[i]:
        ret[ghex(i)] = program.tags[i]['name']
  emit('names', ret, True)

@socketio.on('gotoname', namespace='/qira')
@socket_method
def gotoname(name):
  if False and qira_config.WITH_IDA:
    ea = ida.get_name_ea(name)
    if ea != None:
      emit('setiaddr', ghex(ea))
  else:
    # TODO: very low quality algorithm
    for i in program.tags:
      if 'name' in program.tags[i] and program.tags[i]['name'] == name:
        emit('setiaddr', ghex(i))
        break

# used to set names and comments and stuff
# ['name', 'comment']
@socketio.on('settags', namespace='/qira')
@socket_method
def settags(tags):
  for addr in tags:
    naddr = fhex(addr)
    for i in tags[addr]:
      if qira_config.WITH_IDA:
        if i == 'name':
          ida.set_name(naddr, tags[addr][i])
        elif i == 'comment':
          ida.set_comment(naddr, tags[addr][i])
      program.tags[naddr][i] = tags[addr][i]
      print hex(naddr), i, program.tags[naddr][i]

@socketio.on('getstaticview', namespace='/qira')
@socket_method
def getstaticview(haddr, flat, flatrange):
  addr = fhex(haddr)

# *** OLDER, LESS SUPPORTED STATIC FUNCTIONS ***

@app.route('/gettagsa', methods=["POST"])
def gettagsa():
  arr = json.loads(request.data)
  ret = []
  for i in arr:
    i = fhex(i)
    # always return them all
    # a bit of a hack, this is so javascript can display it
    program.tags[i]['address'] = ghex(i)
    ret.append(program.tags[i])
  return json.dumps(ret)

@socketio.on('gettags', namespace='/qira')
@socket_method
def gettags(start, length):
  start = fhex(start)
  ret = []
  for i in range(start, start+length):
    if len(program.tags[i]) != 0:
      # a bit of a hack, this is so javascript can display it
      program.tags[i]['address'] = ghex(i)
      ret.append(program.tags[i])
  emit('tags', ret, True)

@socketio.on('getstaticview', namespace='/qira')
@socket_method
def getstaticview(haddr, flat, flatrange):
  # disable this to disable static
  if not qira_config.WITH_STATIC:
    return

  addr = fhex(haddr)
  if flat or 'scope' not in program.tags[addr]:
    # not a function, return flat view
    ret = []
    # find backward
    i = addr
    while len(ret) != abs(flatrange[0]):
      did_append = False
      # search up to 256 back
      for j in range(1, 256):
        if 'len' in program.tags[i-j] and program.tags[i-j]['len'] == j:
          i -= j
          program.tags[i]['address'] = ghex(i)
          program.tags[i]['bytes'] = get_static_bytes(i, j, True)
          ret.append(program.tags[i])
          did_append = True
          break
      if not did_append:
        i -= 1
        program.tags[i]['address'] = ghex(i)
        program.tags[i]['bytes'] = get_static_bytes(i, 1, True)
        ret.append(program.tags[i])
    ret = ret[::-1]

    # find forward
    i = addr
    while len(ret) != abs(flatrange[0]) + flatrange[1]:
      program.tags[i]['address'] = ghex(i)
      #print program.tags[i]
      if 'len' in program.tags[i]:
        program.tags[i]['bytes'] = get_static_bytes(i, program.tags[i]['len'], True)
        i += program.tags[i]['len']
      else:
        program.tags[i]['bytes'] = get_static_bytes(i, 1, True)
        i += 1
      ret.append(program.tags[i])
    emit('tags', ret, False)
  else:
    # function
    start = program.tags[addr]['scope']
    length = program.tags[fhex(start)]['funclength']
    gettags(start, length)

# dot as a service
@app.route('/dot', methods=["POST"])
def graph_dot():
  req = request.data
  #print "DOT REQUEST", req
  f = open("/tmp/in.dot", "w")
  f.write(req)
  f.close()
  os.system("dot /tmp/in.dot > /tmp/out.dot")
  ret = open("/tmp/out.dot").read()
  #print "DOT RESPONSE", ret
  return ret

# *** INIT FUNCTIONS ***

def init_radare(path):
  core = RCore()
  desc = core.io.open(path, 0, 0)
  if desc == None:
    print "*** RBIN LOAD FAILED"
    return False
  core.bin.load(path, 0, 0, 0, desc.fd, False)
  print "*** radare bin loaded @",ghex(core.bin.get_baddr())

  """
  for e in core.bin.get_entries():
    print e
  """

  """
  for s in core.bin.get_symbols():
    print ghex(s.vaddr), s.name
  """

  """
  # why do i need to do this?
  info = core.bin.get_info()
  core.config.set("asm.arch", info.arch);
  core.config.set("asm.bits", str(info.bits));
  #core.file_open(path, 0, 0)

  # find functions
  core.search_preludes()
  """

  core.bin_load("", 0)
  core.anal_all()

  import collections
  tags = collections.defaultdict(dict)

  for f in core.anal.get_fcns():
    print f.name, ghex(f.addr), f.size
    """
    for b in f.get_bbs():
      print "  ", ghex(b.addr), ghex(b.size)
    """
      #for i in 


def init_static(lprogram):
  global program
  program = lprogram
  if qira_config.WITH_IDA:
    ida.init_with_binary(program.program)

    tags = ida.fetch_tags()
    print "*** ida returned %d tags" % (len(tags))

    # grr, copied from settags, merge into tags
    for addr in tags:
      for i in tags[addr]:
        program.tags[addr][i] = tags[addr][i]

  if qira_config.WITH_RADARE:
    init_radare(program.program)

  # as a hack, we can assume it's loading at 0x8048000
  # forget sections for now
  # we really need to add a static memory repo
  global elf_dat, load_addr
  elf_dat = open(program.program, "rb").read()
  load_addr = 0x8048000

  # generate the static data for the instruction
  print "** running static"
  for addr in program.tags:
    if 'flags' in program.tags[addr] and program.tags[addr]['flags']&0x600 == 0x600:
      # the question here is where do we get the instruction bytes?
      raw = get_static_bytes(addr, program.tags[addr]['len'])
      # capinstruction, bap
      program.tags[addr]['capinstruction'] = program.disasm(raw, addr)
      #print hex(addr), self.tags[addr]['len'], self.tags[addr]['capinstruction']
      # for now, make it the default
      program.tags[addr]['instruction'] = program.tags[addr]['capinstruction']['repr']

      # BAP IS BALLS SLOW
      #self.tags[addr]['bap'] = self.genbap(raw, addr)
  print "** static done"

if __name__ == "__main__":
  init_radare(sys.argv[1])

