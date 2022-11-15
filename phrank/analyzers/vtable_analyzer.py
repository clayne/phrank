import idaapi
import phrank.util_aux as util_aux

from phrank.analyzers.type_analyzer import TypeAnalyzer
from phrank.containers.vtable import Vtable

class VtableAnalyzer(TypeAnalyzer):
	def get_gvar_vtable(self, gvar_ea):
		gvar_tinfo = self.get_gvar_tinfo(gvar_ea)
		if gvar_tinfo is None:
			return None

		gvar_strucid = Vtable.get_existing_strucid(gvar_tinfo)
		if gvar_strucid == idaapi.BADADDR:
			return None

		if Vtable.is_vtable(gvar_strucid):
			return Vtable(gvar_ea, gvar_strucid)
		return None

	def analyze_gvar(self, gvar_ea):
		vtbl = self.gvar2tinfo.get(gvar_ea)
		if vtbl is not None:
			return vtbl

		# trying to initialize from type at address
		vtbl = Vtable.get_vtable_at_address(gvar_ea)
		if vtbl is not None:
			tif = vtbl.get_tinfo()
			self.gvar2tinfo[gvar_ea] = tif
			return tif

		vfcs = Vtable.get_vtable_functions_at_addr(gvar_ea)
		if len(vfcs) == 0:
			return None

		vtbl_name = "vtable_" + hex(gvar_ea)[2:]
		vtbl_name = util_aux.get_next_available_strucname(vtbl_name)
		vtbl = Vtable(struc_locator=vtbl_name, vtbl_funcs=vfcs)
		self.new_types.append(vtbl.strucid)
		tif = vtbl.get_tinfo()
		self.gvar2tinfo[gvar_ea] = tif
		return tif

	def analyze_everything(self):
		for segstart, segend in util_aux.iterate_segments():
			self.analyze_segment(segstart, segend)

	def analyze_segment(self, segstart, segend):
		ptr_size = util_aux.get_ptr_size()
		while segstart < segend:
			vtbl = self.analyze_gvar(segstart)
			if vtbl is None:
				segstart += ptr_size
			else:
				segstart += vtbl.get_size()