from __future__ import annotations

import idaapi
import ida_struct
import idc
from functools import lru_cache as _lru_cache


UNKNOWN_TYPE = idaapi.tinfo_t()


def is_tif_pointer(tif:idaapi.tinfo_t) -> bool:
	return tif.is_ptr() or tif.is_array()

def get_pointer_object(tif:idaapi.tinfo_t) -> idaapi.tinfo_t:
	if tif.is_ptr():
		return tif.get_pointed_object()
	elif tif.is_array():
		return tif.get_array_element()
	else:
		raise TypeError("Tif is not a pointer " + str(tif))

def get_final_tif(tif:idaapi.tinfo_t) -> idaapi.tinfo_t:
	while is_tif_pointer(tif):
		tif = get_pointer_object(tif)
	return tif

def is_tif_correct(tif:idaapi.tinfo_t) -> bool:
	if not tif.is_correct():
		return False

	if str(tif) == "":
		return False
	return True

def str2strucid(s:str) -> int:
	if s.startswith("struct "):
		s = s[7:]

	rv = idaapi.get_struc_id(s)
	if rv != idaapi.BADADDR:
		return rv

	rv = idaapi.import_type(idaapi.get_idati(), -1, s)
	if rv == idaapi.BADNODE:
		return idaapi.BADADDR
	return rv

def tif2strucid(tif:idaapi.tinfo_t) -> int:
	tif = get_final_tif(tif)
	if not is_tif_correct(tif):
		return idaapi.BADADDR

	if tif.is_struct():
		return str2strucid(str(tif))

	if tif.is_integral() or tif.is_void() or tif.is_func() or tif.is_enum() or tif.is_bool():
		return idaapi.BADADDR

	print("WARNING: unknown tinfo2strucid", tif)
	return idaapi.BADADDR


def addr2tif(addr:int) -> idaapi.tinfo_t:
	addr_type = idc.get_type(addr)
	if addr_type is None:
		return None

	return str2tif(addr_type)


@_lru_cache
def str2tif(type_str:str) -> idaapi.tinfo_t|None:
	if type_str[-1] != ';': type_str = type_str + ';'

	tinfo = idaapi.tinfo_t()
	idaapi.parse_decl(tinfo, idaapi.get_idati(), type_str, 0)
	if not tinfo.is_correct():
		print("[*] WARNING: Failed to parse type: {}".format(type_str))
		return None
	return tinfo

def get_int_tinfo(size:int=1) -> idaapi.tinfo_t:
	char_tinfo = idaapi.tinfo_t()
	if size == 2:
		idaapi.parse_decl(char_tinfo, idaapi.get_idati(), "unsigned short;", 0)
	elif size == 4:
		idaapi.parse_decl(char_tinfo, idaapi.get_idati(), "unsigned int;", 0)
	else:
		idaapi.parse_decl(char_tinfo, idaapi.get_idati(), "unsigned char;", 0)
	assert char_tinfo.is_correct()
	return char_tinfo

# inner *__shifted(outer, offset)
def make_shifted_ptr(outer:idaapi.tinfo_t, inner:idaapi.tinfo_t, offset:int) -> idaapi.tinfo_t:
	shifted_tif = idaapi.tinfo_t()
	pi = idaapi.ptr_type_data_t()
	pi.taptr_bits = idaapi.TAPTR_SHIFTED
	pi.delta = offset
	pi.parent = outer
	pi.obj_type = inner
	shifted_tif.create_ptr(pi)
	return shifted_tif

def get_shifted_base(shifted:idaapi.tinfo_t):
	if not shifted.is_shifted_ptr():
		return None, -1

	pi = idaapi.ptr_type_data_t()
	if not shifted.get_ptr_details(pi):
		return None, -1
	return pi.parent, pi.delta


class ShiftedStruct:
	""" Analog of shifted pointers but not for pointers"""
	def __init__(self, strucid, offset):
		self.strucid = strucid
		self.offset = offset

	@property
	def name(self) -> str:
		name = idc.get_member_name(self.strucid, self.offset)
		if name is None: name = ""
		return name

	@property
	def tif(self) -> idaapi.tinfo_t:
		sptr = ida_struct.get_struc(self.strucid)
		mptr = ida_struct.get_member(sptr, self.offset)
		# member is unset
		if mptr is None:
			return UNKNOWN_TYPE

		tif = idaapi.tinfo_t()
		# member has no type
		if not ida_struct.get_member_tinfo(tif, mptr):
			return UNKNOWN_TYPE
		return tif

	@property
	def comment(self) -> str:
		cmt = idc.get_member_cmt(self.strucid, self.offset, 0)
		if cmt is None: cmt = ""
		return cmt

	def __str__(self) -> str:
		return f"MEMBEROF({idc.get_struc_name(self.strucid)},{hex(self.offset)})"

def get_tif_member(tif:idaapi.tinfo_t, offset:int) -> ShiftedStruct|None:
	strucid = tif2strucid(tif)
	if strucid == idaapi.BADADDR:
		return None

	return ShiftedStruct(strucid, offset)