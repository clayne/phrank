import idaapi


ARRAY_FUNCS = {"qmemcpy", "memcpy", "strncpy", "memset", "memmove", "strncat", "strncmp"}
ARRAY_FUNCS.update(['_' + s for s in ARRAY_FUNCS])

WARRAY_FUNCS = {"wcsncat", "wcsncpy"}
WARRAY_FUNCS.update(['_' + s for s in WARRAY_FUNCS])

PRINTF_FUNCS = {"vsnprintf", "snprintf"}
PRINTF_FUNCS.update(['_' + s for s in PRINTF_FUNCS])

HELPER_FUNCS = {"LOWORD", "HIWORD", "LOBYTE"}


def get_var_write(expr):
	if expr.op == idaapi.cot_var:
		return expr.v

	if expr.op == idaapi.cot_call and expr.x.op == idaapi.cot_helper:
		func = expr.x.helper
		if func in HELPER_FUNCS:
			arg0 = expr.a[0]
			if arg0.op == idaapi.cot_var:
				return arg0.v

	if expr.op == idaapi.cot_ptr and expr.x.op == idaapi.cot_cast:
		if expr.x.x.op == idaapi.cot_ref and expr.x.x.x.op == idaapi.cot_var:
			return expr.x.x.x.v

	return None

def get_var_access(expr):
	if expr.op == idaapi.cot_cast:
		return get_var_access(expr.x)

	if expr.op == idaapi.cot_memptr and expr.x.op == idaapi.cot_var:
		return expr.x.v, expr.m + expr.x.type.get_size()

	if expr.op == idaapi.cot_idx:
		if expr.x.op != idaapi.cot_var or expr.y.op != idaapi.cot_num:
			return None

		return expr.x.v, (expr.y.n._value + 1) * expr.x.type.get_size()

	if expr.op == idaapi.cot_ptr:
		return get_var_offset(expr.x)

	return None

def get_varptr_write_offset(expr):
	if expr.op == idaapi.cot_idx:
		if expr.x.op != idaapi.cot_var or expr.y.op != idaapi.cot_num:
			return None

		return expr.x.v, expr.y.n._value * expr.x.type.get_size()

	if expr.op == idaapi.cot_ptr:
		return get_var_offset(expr.x)

	if expr.op == idaapi.cot_memptr and expr.x.op == idaapi.cot_var:
		return expr.x.v, expr.m

	return None

# trying to get various forms of "var + X", where X is int
def get_var_offset(expr):
	if expr.op == idaapi.cot_cast:
		return get_var_offset(expr.x)

	elif expr.op == idaapi.cot_var:
		return expr.v, 0

	# form ((CASTTYPE*)var) + N
	elif expr.op in [idaapi.cot_add, idaapi.cot_sub]:
		if expr.y.op != idaapi.cot_num:
			return None
		offset = expr.y.n._value
		if expr.op == idaapi.cot_sub:
			offset = - offset

		op_x = expr.x
		if op_x.op == idaapi.cot_var:
			var = op_x.v

		elif op_x.op == idaapi.cot_cast and op_x.x.op == idaapi.cot_var:
			var = op_x.x.v

		else:
			return None

		if op_x.type.is_ptr():
			sz = op_x.type.get_pointed_object().get_size()
			if sz == idaapi.BADSIZE: 
				raise BaseException("Failed to get object's size")
			offset = offset * sz

		return var, offset

	else:
		return None

def get_int(expr):
	if expr.op == idaapi.cot_cast:
		return get_int(expr.x)

	if expr.op == idaapi.cot_ref and expr.x.op == idaapi.cot_obj:
		return expr.x.obj_ea

	if expr.op == idaapi.cot_obj:
		return expr.obj_ea

	if expr.op == idaapi.cot_num:
		return expr.n._value

	return None