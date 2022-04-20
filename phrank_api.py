import idaapi

import phrank.phrank_cpp as phrank_cpp
import phrank.phrank_util as phrank_util
import phrank.phrank_func as phrank_func
import phrank.phrank_settings as phrank_settings
import phrank.phrank_containers as phrank_containers
import phrank.phrank_hexrays as phrank_hexrays
import phrank.phrank_struct_analysis as struct_analysis

import time

def clear_caches():
	phrank_func.FuncWrapper.clear_cached_instances()
	phrank_hexrays.FuncAnalysisVisitor.clear_cached_instances()

def analysis_api(func):
	def fwrapper(*args, **kwargs):
		clear_caches()
		rv = func(*args, **kwargs)
		clear_caches()
		return rv
	return fwrapper

@analysis_api
def analyze_everything():
	phrank_cpp.CppClassFactory().analyze_everything()

@analysis_api
def analyze_func(addr):
	phrank_cpp.CppClassFactory().analyze_func(addr)

@analysis_api
def analyze_vtable(addr):
	phrank_cpp.CppClassFactory().analyze_vtable(addr)

@analysis_api
def analyze_variable(cfunc, var):
	struct_analysis.StructFactory().analyze_variable(cfunc, var)

@analysis_api
def create_cpp_vtables():
	phrank_cpp.CppVtableFactory().create_all_vtables()

@analysis_api
def create_vtables():
	phrank_containers.VtableFactory().create_all_vtables()

def create_vtable(addr):
	factory = phrank_containers.VtableFactory()
	return factory.create_vtable(addr=addr)

def citem_to_int(cfunc, citem):
	if citem.citype != idaapi.VDI_EXPR:
		return idaapi.BADADDR

	expr = citem.it.to_specific_type

	parent_asg = expr
	while parent_asg is not None:
		if parent_asg.op == idaapi.cot_asg:
			break
		parent_asg = cfunc.body.find_parent_of(parent_asg).to_specific_type

	if parent_asg is None:
		return idaapi.BADADDR

	intval = phrank_hexrays.get_int(parent_asg.y)
	if intval is None:
		return idaapi.BADADDR

	return intval

def should_skip_decompiling(func_wrapper):
	fname = func_wrapper.get_name()
	if fname is None:
		print("emtpy name %s" % hex(func_wrapper.get_start()))
		return True

	if phrank_settings.should_skip_by_prefix(fname):
		return True

	# global constructors
	if fname.startswith("_GLOBAL__sub_I_"):
		return True

	dfname = idaapi.demangle_name(fname, idaapi.MNG_NODEFINIT | idaapi.MNG_NORETTYPE)
	if dfname is not None and phrank_settings.should_skip_by_prefix(dfname):
		return True

	return False

def decompile_wrappers(fwrappers):
	time_amount = time.time()
	for fw in fwrappers:
		fw.decompile()
	time_amount = time.time() - time_amount

	print("decompiling", len(fwrappers), "took", round(time_amount, 3))

def decompile_all():
	fwrappers = [phrank_func.FuncWrapper(addr=fea) for fea in phrank_util.iterate_all_functions()]
	fwrappers = filter(None, fwrappers)
	fwrappers = filter(lambda x: not should_skip_decompiling(x), fwrappers)
	fwrappers = list(fwrappers)
	phrank_settings.DECOMPILE_RECURSIVELY = True
	decompile_wrappers(fwrappers)
	phrank_settings.DECOMPILE_RECURSIVELY = False
