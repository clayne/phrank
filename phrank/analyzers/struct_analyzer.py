from __future__ import annotations

import idaapi

import phrank.utils as utils

from phrank.analyzers.type_analyzer import TypeAnalyzer
from phrank.analyzers.vtable_analyzer import VtableAnalyzer
from phrank.containers.structure import Structure
from phrank.ast_parts import *


class StructAnalyzer(TypeAnalyzer):
	def __init__(self, func_factory=None) -> None:
		super().__init__(func_factory)
		self.analyzed_functions = set()
		self.vtable_analyzer = VtableAnalyzer(func_factory)

	def add_type_uses(self, var_uses:VarUses, var_type:idaapi.tinfo_t):
		for var_write in var_uses.writes:
			if var_write.is_assign(): continue
			self.add_type_use(var_type, var_write, var_write.value_type)

		for var_read in var_uses.reads:
			self.add_type_use(var_type, var_read, utils.UNKNOWN_TYPE)

		for cast in var_uses.casts:
			# FIXME kostyl
			if cast.is_var_arg():
				continue

			arg_type = cast.arg_type
			if arg_type.is_ptr():
				arg_type = arg_type.get_pointed_object()

			self.add_type_use(var_type, cast, arg_type)

	def add_type_use(self, var_type:idaapi.tinfo_t, vuc:VarUseChain, member_type:idaapi.tinfo_t):
		if var_type.is_ptr():
			var_type = var_type.get_pointed_object()
			if var_type.is_struct():
				strucid = utils.tif2strucid(var_type)
				offset = vuc.get_ptr_offset()
				if offset is None:
					return
				self.add_member_type(strucid, offset, member_type)

	def add_member_type(self, strucid:int, offset:int, member_type:idaapi.tinfo_t):
		# do not modificate existing types
		if strucid not in self.new_types:
			return

		lvar_struct = Structure(strucid)

		# use of the member exists, thus there should be the field
		if not lvar_struct.member_exists(offset):
			lvar_struct.add_member(offset)

		# if unknown, then simply creating new member is enough
		if member_type is utils.UNKNOWN_TYPE:
			return

		next_offset = lvar_struct.get_next_member_offset(offset)
		if next_offset != -1 and offset + member_type.get_size() > next_offset:
			# TODO remove when struct sizes are remembered
			# currently struct size is set by adding 1byte int at the end
			# if that is the case, then allow member type setting
			if lvar_struct.get_member_size(next_offset) != 1 or lvar_struct.size != next_offset + 1:
				print(
					"WARNING: failed to change type of",
					lvar_struct.name, "at", hex(offset),
					"to", str(member_type),
					"because it overwrites next field at",
					hex(next_offset), "skipping member type change",
				)
				return

		member_offset = lvar_struct.get_member_start(offset)
		current_type = lvar_struct.get_member_tinfo(offset)
		if  current_type is not None and \
			current_type.is_struct() and \
			current_type.get_size() > member_type.get_size():

			strucid = utils.tif2strucid(current_type)
			self.add_member_type(strucid, offset - member_offset, member_type)
		else:
			lvar_struct.set_member_type(offset, member_type)

	def apply_analysis(self):
		var_to_propagate = []
		for func_ea, lvar_id in self.lvar2tinfo.keys():
			var_to_propagate.append(Var(func_ea, lvar_id))

		for obj_ea in self.gvar2tinfo.keys():
			var_to_propagate.append(Var(obj_ea))

		for var in var_to_propagate:
			self.propagate_var(var)

		touched_functions = set()
		for func_ea, _ in self.lvar2tinfo.keys():
			touched_functions.add(func_ea)

		for obj_ea in self.gvar2tinfo.keys():
			touched_functions.update(utils.get_func_calls_to(obj_ea))

		for func_ea in touched_functions:
			func_aa = self.get_ast_analysis(func_ea)
			for func_call in func_aa.calls:
				if not func_call.is_implicit(): continue

				frm = func_call.call_expr.ea
				if frm == idaapi.BADADDR:
					continue

				call_ea = self.calculate_implicit_func_call_address(func_call)
				if call_ea == -1:
					continue

				self.new_xrefs.append((frm, call_ea))

		super().apply_analysis()
		self.vtable_analyzer.apply_analysis()

	def clear_analysis(self):
		super().clear_analysis()
		self.vtable_analyzer.clear_analysis()

	def get_lvar_uses(self, func_ea:int, lvar_id:int):
		var_uses = VarUses()
		func_aa = self.get_ast_analysis(func_ea)
		for var_read in func_aa.iterate_lvar_reads(func_ea, lvar_id):
			var_uses.reads.append(var_read)
		for var_write in func_aa.iterate_lvar_writes(func_ea, lvar_id):
			var_uses.writes.append(var_write)
		for call_cast in func_aa.iterate_lvar_call_casts(func_ea, lvar_id):
			var_uses.casts.append(call_cast)
		return var_uses

	def analyze_lvar_uses(self, func_ea:int, lvar_id:int, var_uses:VarUses):
		for var_write in var_uses.writes:
			var_write.value_type = self.analyze_cexpr(func_ea, var_write.value)
		for call_cast in var_uses.casts:
			address = call_cast.func_call.address
			if address == -1:
				continue

			call_cast.arg_type = self.analyze_lvar(address, call_cast.arg_id)

	def analyze_gvar_type_by_assigns(self, gvar_ea:int) -> idaapi.tinfo_t:
		# analyzing gvar type by assigns to it
		funcs = set(utils.get_func_calls_to(gvar_ea))
		assigns = []
		for func_ea in funcs:
			aa = self.get_ast_analysis(func_ea)
			for ga in aa.iterate_gvar_writes(gvar_ea):
				if ga.is_assign():
					assigns.append((func_ea, ga))

		if len(assigns) != 1:
			return utils.UNKNOWN_TYPE

		assign_ea, gvar_assign = assigns[0]
		return self.analyze_cexpr(assign_ea, gvar_assign.value)

	def analyze_gvar(self, gvar_ea:int) -> idaapi.tinfo_t:
		current_type = self.gvar2tinfo.get(gvar_ea)
		if current_type is not None:
			return current_type

		vtbl = self.vtable_analyzer.analyze_gvar(gvar_ea)
		if vtbl is not utils.UNKNOWN_TYPE:
			return vtbl

		gvar_type = self.analyze_gvar_type_by_assigns(gvar_ea)
		self.gvar2tinfo[gvar_ea] = gvar_type
		return gvar_type

	def analyze_tif_use_chain(self, tif:idaapi.tinfo_t, chain:list[VarUse]):
		if len(chain) == 0:
			return tif
		return utils.UNKNOWN_TYPE

	def analyze_cexpr(self, func_ea:int, cexpr:idaapi.cexpr_t) -> idaapi.tinfo_t:
		cexpr = utils.strip_casts(cexpr)

		if cexpr.op == idaapi.cot_var:
			return self.analyze_lvar(func_ea, cexpr.v.idx)

		if cexpr.op == idaapi.cot_call and cexpr.x.op == idaapi.cot_obj and utils.is_func_start(cexpr.x.obj_ea):
			call_ea = cexpr.x.obj_ea
			return self.analyze_retval(call_ea)

		if cexpr.op in {idaapi.cot_num}:
			return cexpr.type

		if cexpr.op == idaapi.cot_obj and not utils.is_func_start(cexpr.obj_ea):
			gvar_type = self.analyze_gvar(cexpr.obj_ea)
			if gvar_type is utils.UNKNOWN_TYPE:
				return utils.UNKNOWN_TYPE

			actual_type = utils.addr2tif(cexpr.obj_ea)
			if actual_type is None or actual_type.is_array():
				gvar_ptr_type = idaapi.tinfo_t()
				gvar_ptr_type.create_ptr(gvar_type)
				gvar_type = gvar_ptr_type
			return gvar_type

		if cexpr.op == idaapi.cot_ref and cexpr.x.op == idaapi.cot_obj and not utils.is_func_start(cexpr.x.obj_ea):
			gvar_type = self.analyze_gvar(cexpr.x.obj_ea)
			if gvar_type is utils.UNKNOWN_TYPE:
				return utils.UNKNOWN_TYPE

			gvar_ptr_type = idaapi.tinfo_t()
			gvar_ptr_type.create_ptr(gvar_type)
			return gvar_ptr_type

		print("WARNING:", "unknown cexpr value", cexpr.opname)
		return utils.UNKNOWN_TYPE

	def calculate_var_type_by_uses(self, var_uses: VarUses):
		if len(var_uses) == 0:
			print("WARNING:", "found no var uses")
			return utils.UNKNOWN_TYPE

		casts = var_uses.casts
		writes = var_uses.writes
		reads = var_uses.reads

		assigns = [w for w in writes if w.is_assign()]
		# single assign can only be one type
		if len(assigns) == 1:
			return assigns[0].value_type

		# try to resolve multiple assigns
		if len(assigns) > 1:
			# prefer types over non-types
			strucid_assign_types = []
			for a in assigns:
				if a.value_type is utils.UNKNOWN_TYPE:
					continue
				strucid = utils.tif2strucid(a.value_type)
				if strucid != idaapi.BADADDR:
					strucid_assign_types.append(a.value_type)

			if len(strucid_assign_types) == 1:
				return strucid_assign_types[0]
			# multiple different assignments is unknown
			else:
				return utils.UNKNOWN_TYPE

		# weeding out non-pointers
		for w in writes:
			if not w.is_possible_ptr():
				print("non-pointer writes are not supported for now", w)
				return utils.UNKNOWN_TYPE

		# weeding out non-pointers2
		for c in casts:
			if c.is_possible_ptr() is None:
				print("non-pointer casts are not supported for now", c)
				return utils.UNKNOWN_TYPE

		# weeding out non-pointers3
		for r in reads:
			if not r.is_possible_ptr():
				print("non-pointer reads are not supported for now", r)
				return utils.UNKNOWN_TYPE

		# single write at offset 0 does not create new type
		if len(var_uses) == 1 and len(writes) == 1 and writes[0].get_ptr_offset() == 0:
			write_type = writes[0].value_type.copy()
			write_type.create_ptr(write_type)
			return write_type

		# single cast at offset 0 might be existing type
		if len(casts) == 1 and casts[0].is_var_arg():
			arg_type = casts[0].arg_type

			# casting to something unknown yield unknown
			if arg_type is utils.UNKNOWN_TYPE:
				return utils.UNKNOWN_TYPE

			# simple variable passing does not create new type
			if len(writes) == 0:
				return arg_type

			# single cast and writes into casted type
			if arg_type.is_ptr():
				arg_type = arg_type.get_pointed_object()

			# checking that writes do not go outside of casted value
			cast_end = arg_type.get_size()
			for w in writes:
				write_start = w.get_ptr_offset()
				if write_start is None:
					continue
				write_end = w.value_type.get_size()
				# write_start, write_end = w[0], w[1].get_size()
				if write_start < 0 or write_end > cast_end:
					return utils.UNKNOWN_TYPE

			arg_type.create_ptr(arg_type)
			return arg_type

		# TODO writes into array of one type casts, that start at offset 0
		# TODO check if all writes are to the same offset
		# TODO check if all writes are actually array writes at various offsets

		# all cases ended, assuming new structure pointer
		lvar_struct = Structure.create()
		self.new_types.add(lvar_struct.strucid)
		lvar_tinfo = lvar_struct.ptr_tinfo
		return lvar_tinfo

	def get_current_var_type(self, var:Var):
		if var.is_local():
			return self.get_var_type(*var.varid)
		else:
			return utils.addr2tif(var.varid)

	def set_var_type(self, var:Var, var_tinfo:idaapi.tinfo_t):
		if var.is_local():
			self.lvar2tinfo[var.varid] = var_tinfo
		else:
			self.gvar2tinfo[var.varid] = var_tinfo

	def analyze_var(self, var:Var) -> idaapi.tinfo_t:
		if var.is_local():
			return self.analyze_lvar(*var.varid)
		else:
			return self.analyze_gvar(var.varid)

	def analyze_lvar(self, func_ea:int, lvar_id:int) -> idaapi.tinfo_t:
		current_lvar_tinfo = self.lvar2tinfo.get((func_ea, lvar_id))
		if current_lvar_tinfo is not None:
			return current_lvar_tinfo

		lvar = self.get_lvar(func_ea, lvar_id)
		if lvar is not None and lvar.is_stk_var() and not lvar.is_arg_var:
			print("WARNING: variable", lvar.name, "in", idaapi.get_name(func_ea), "is stack variable, whose analysis is not yet implemented")
			return utils.UNKNOWN_TYPE

		lvar_tinfo = self.get_var_type(func_ea, lvar_id)
		if utils.is_func_import(func_ea):
			return lvar_tinfo

		if lvar_tinfo is not utils.UNKNOWN_TYPE and utils.tif2strucid(lvar_tinfo) != idaapi.BADADDR:
			# TODO check correctness of writes, read, casts
			return lvar_tinfo

		# TODO check that var is not recursively dependant on itself
		# TODO check that var uses are compatible
		lvar_uses = self.get_lvar_uses(func_ea, lvar_id)
		self.analyze_lvar_uses(func_ea, lvar_id, lvar_uses)
		lvar_tinfo = self.calculate_var_type_by_uses(lvar_uses)
		if lvar_tinfo is not utils.UNKNOWN_TYPE and utils.tif2strucid(lvar_tinfo) != idaapi.BADADDR:
			self.add_type_uses(lvar_uses, lvar_tinfo)
		self.lvar2tinfo[(func_ea, lvar_id)] = lvar_tinfo
		return lvar_tinfo

	def analyze_retval(self, func_ea:int) -> idaapi.tinfo_t:
		rv = self.retval2tinfo.get(func_ea)
		if rv is not None:
			return rv

		aa = self.get_ast_analysis(func_ea)
		r_types = []
		for r in aa.returns:
			var_type = self.analyze_var(r.var)
			if var_type is utils.UNKNOWN_TYPE:
				r_types.append(utils.UNKNOWN_TYPE)
				continue

			r_type = self.analyze_tif_use_chain(var_type, r.uses)
			if r_type is utils.UNKNOWN_TYPE:
				print("WARNING: failed to analyze retval chain", utils.expr2str(r.retval))
			r_types.append(r_type)

		if len(r_types) == 1:
			retval_type = r_types[0]
		elif len(r_types) == 0:
			retval_type = utils.UNKNOWN_TYPE
		else:
			rv0 = r_types[0]
			for i in range(1, len(r_types)):
				if r_types[i] != rv0:
					print(
						"WARNING: multiple retval types are not supported",
						hex(func_ea), idaapi.get_name(func_ea)
					)
					retval_type = utils.UNKNOWN_TYPE
					break
			else:
				retval_type = rv0

		self.retval2tinfo[func_ea] = retval_type
		return retval_type

	def analyze_function(self, func_ea:int):
		if func_ea in self.analyzed_functions:
			return
		self.analyzed_functions.add(func_ea)

		for call_from_ea in utils.get_func_calls_from(func_ea):
			self.analyze_function(call_from_ea)

		for i in range(self.get_lvars_counter(func_ea)):
			self.analyze_lvar(func_ea, i)

		self.analyze_retval(func_ea)

	def is_ok_propagation_type(self, tif:idaapi.tinfo_t) -> bool:
		if tif is None or tif is utils.UNKNOWN_TYPE:
			return False
		strucid = utils.tif2strucid(tif)
		if strucid not in self.new_types:
			return False
		return True

	def get_var_tinfo(self, var:Var) -> idaapi.tinfo_t:
		if var.is_local():
			return self.lvar2tinfo.get(var.varid, utils.UNKNOWN_TYPE)
		else:
			return self.gvar2tinfo.get(var.varid, utils.UNKNOWN_TYPE)

	def calculate_implicit_func_call_address(self, func_call:FuncCall) -> int:
		vuc = func_call.implicit_var_use_chain
		if vuc is None:
			return -1

		var_tif = self.get_var_tinfo(vuc.var)
		if var_tif is utils.UNKNOWN_TYPE:
			return -1

		final = vuc.get_final_tif(var_tif)
		if isinstance(final, idaapi.udt_member_t):
			addr = utils.str2addr(final.cmt) # type:ignore
			if addr == -1:
				addr = utils.str2addr(final.name) # type:ignore
		else:
			addr = -1
			print("WARNING:", f"failed to get final member from {var_tif} {[str(x) for x in vuc.uses]}")

		if addr == -1:
			print("WARNING: unknown implicit call", utils.expr2str(func_call.call_expr, hide_casts=True))
		return addr

	def propagate_var_type_in_casts(self, var_type:idaapi.tinfo_t, casts:list[CallCast]):
		for call_cast in casts:
			func_call = call_cast.func_call
			call_ea = -1
			if func_call.is_explicit():
				call_ea = func_call.address
			elif func_call.is_implicit():
				call_ea = self.calculate_implicit_func_call_address(func_call)

			if call_ea == -1:
				continue

			if utils.is_func_import(call_ea):
				continue

			if not call_cast.is_var_arg():
				continue

			arg_id = call_cast.arg_id
			current_type = self.lvar2tinfo.get((call_ea, arg_id), utils.UNKNOWN_TYPE)
			if current_type is utils.UNKNOWN_TYPE:
				lvar_uses = self.get_lvar_uses(call_ea, arg_id)
				func_aa = self.get_ast_analysis(arg_id)
				arg_assigns = [w for w in func_aa.iterate_lvar_writes(call_ea, arg_id) if w.is_assign()]
				if len(arg_assigns) != 0:
					continue

				self.lvar2tinfo[(call_ea, arg_id)] = var_type
				self.propagate_var(Var(call_ea, arg_id))
				self.add_type_uses(lvar_uses, var_type)
				continue

			if current_type != var_type:
				print(
					"Failed to propagate", str(var_type),
					"to", self.get_lvar_name(call_ea, arg_id),
					"in", idaapi.get_name(call_ea),
					"because variable has different type", current_type,
				)

	def get_var_call_casts(self, var:Var):
		if var.is_local():
			aa = self.get_ast_analysis(var.varid[0])
			casts = [c for c in aa.iterate_lvar_call_casts(*var.varid)]
		else:
			funcs = set(utils.get_func_calls_to(var.varid))
			casts = []
			for func_ea in funcs:
				aa = self.get_ast_analysis(func_ea)
				for call_cast in aa.iterate_gvar_call_casts(var.varid):
					casts.append(call_cast)
		return casts

	def propagate_var(self, var:Var):
		var_type = self.get_var_tinfo(var)
		if var_type is utils.UNKNOWN_TYPE:
			return

		if utils.tif2strucid(var_type) not in self.new_types:
			return

		casts = self.get_var_call_casts(var)
		self.propagate_var_type_in_casts(var_type, casts)