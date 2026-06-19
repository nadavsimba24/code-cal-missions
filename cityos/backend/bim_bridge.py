"""
CityOS — BIM Bridge v2
Uses ifcopenshell.api (higher-level) for reliable IFC generation.
"""

import ifcopenshell
import ifcopenshell.api as api
import json, math, uuid, os
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════
# BCF
# ═══════════════════════════════════════════════════════════════════════

class BCFTopic:
    def __init__(self, title, description="", status="open", assigned_to="",
                 priority="medium", ifc_element_guid="", viewpoint=None):
        self.guid = str(uuid.uuid4())
        self.title = title
        self.description = description
        self.status = status
        self.assigned_to = assigned_to
        self.priority = priority
        self.ifc_element_guid = ifc_element_guid
        self.viewpoint = viewpoint or {}
        self.created_at = datetime.now().isoformat()
    
    def to_dict(self):
        return {"guid": self.guid, "title": self.title, "description": self.description,
                "status": self.status, "assigned_to": self.assigned_to,
                "priority": self.priority, "ifc_element_guid": self.ifc_element_guid,
                "viewpoint": self.viewpoint, "created_at": self.created_at}

# ═══════════════════════════════════════════════════════════════════════
# IFC Builder
# ═══════════════════════════════════════════════════════════════════════

class IFCBuilder:
    """Build IFC 4 models from CityOS board/task data, using ifcopenshell.api."""
    
    def __init__(self, project_name="CityOS Project"):
        self.f = ifcopenshell.file()
        self.project = None
        self.body_context = None
        self.elements = {}  # task_id -> (element, guid)
        self._init_project(project_name)
    
    def _init_project(self, name):
        self.project = api.run('root.create_entity', self.f, ifc_class='IfcProject', name=name)
        api.run('unit.assign_unit', self.f, length={'is_metric': True, 'raw': 'METRE'})
        ctx3d = api.run('context.add_context', self.f, context_type='Model')
        self.body_context = api.run('context.add_context', self.f,
            context_type='Model', context_identifier='Body',
            target_view='MODEL_VIEW', parent=ctx3d)
        # Site + Building
        site = api.run('root.create_entity', self.f, ifc_class='IfcSite', name='Site')
        api.run('aggregate.assign_object', self.f, products=[site], relating_object=self.project)
        building = api.run('root.create_entity', self.f, ifc_class='IfcBuilding', name='Building')
        api.run('aggregate.assign_object', self.f, products=[building], relating_object=site)
    
    def _placement(self, x=0, y=0, z=0, angle=0):
        c, s = math.cos(angle), math.sin(angle)
        origin = self.f.createIfcCartesianPoint((float(x), float(y), float(z)))
        axis = self.f.createIfcDirection((0., 0., 1.))
        ref = self.f.createIfcDirection((float(c), float(s), 0.))
        a2p = self.f.createIfcAxis2Placement3D(origin, axis, ref)
        return self.f.createIfcLocalPlacement(None, a2p)
    
    def _create_element(self, name, obj_type, psets=None):
        elem = api.run('root.create_entity', self.f, ifc_class='IfcBuildingElementProxy', name=name)
        # Set ObjectType directly
        elem.ObjectType = obj_type
        return elem
    
    def _add_box_mesh(self, element, w, d, h):
        """Add a 3D box mesh using IfcFacetedBrep."""
        hw, hd, hh = w/2, d/2, h/2
        verts = [(-hw,-hd,-hh),(hw,-hd,-hh),(hw,hd,-hh),(-hw,hd,-hh),
                 (-hw,-hd,hh),(hw,-hd,hh),(hw,hd,hh),(-hw,hd,hh)]
        # 6 face groups, each with 2 triangles referencing the same verts
        face_data = [[(0,1,2),(0,2,3)],[(5,4,7),(5,7,6)],[(1,0,4),(1,4,5)],
                     [(3,2,6),(3,6,7)],[(0,3,7),(0,7,4)],[(2,1,5),(2,5,6)]]
        api.run('geometry.assign_representation', self.f, product=element,
            representation=api.run('geometry.add_mesh_representation', self.f,
                context=self.body_context,
                vertices=[verts]*6, faces=face_data))
    
    def _add_pset(self, element, pset_name, properties):
        """Add property set."""
        props = []
        for k, v in properties.items():
            if isinstance(v, str):
                props.append(self.f.createIfcPropertySingleValue(k, None, self.f.createIfcText(v), None))
            elif isinstance(v, (int, float)):
                props.append(self.f.createIfcPropertySingleValue(k, None, self.f.createIfcLengthMeasure(float(v)), None))
        pset = self.f.createIfcPropertySet(ifcopenshell.guid.new(), None, pset_name, None, props)
        self.f.createIfcRelDefinesByProperties(ifcopenshell.guid.new(), None, None, None, [element], pset)
    
    # ── Model Elements ───────────────────────────────────────────────
    
    def add_road(self, name, start_xy, end_xy, width=6, height=0.2, task_id=""):
        sx, sy = start_xy
        ex, ey = end_xy
        mx, my = (sx+ex)/2, (sy+ey)/2
        length = math.sqrt((ex-sx)**2 + (ey-sy)**2)
        angle = math.atan2(ey-sy, ex-sx)
        elem = self._create_element(name, "Road")
        elem.ObjectPlacement = self._placement(mx, my, 0, angle)
        self._add_box_mesh(elem, length, width, height)
        self._add_pset(elem, "CityOS_Task", {"TaskID": task_id, "Width": width, "Length": length})
        guid = str(elem.GlobalId)
        self.elements[task_id] = guid
        return guid
    
    def add_building(self, name, x, y, w=20, d=15, h=10, task_id=""):
        elem = self._create_element(name, "Building")
        elem.ObjectPlacement = self._placement(x, y, 0)
        self._add_box_mesh(elem, w, d, h)
        self._add_pset(elem, "CityOS_Task", {"TaskID": task_id})
        guid = str(elem.GlobalId)
        self.elements[task_id] = guid
        return guid
    
    def add_infra(self, name, x, y, elem_type="Infrastructure", w=1, d=1, h=3, task_id=""):
        elem = self._create_element(name, elem_type)
        elem.ObjectPlacement = self._placement(x, y, 0)
        self._add_box_mesh(elem, w, d, h)
        self._add_pset(elem, "CityOS_Task", {"TaskID": task_id})
        guid = str(elem.GlobalId)
        self.elements[task_id] = guid
        return guid
    
    # ── Export ───────────────────────────────────────────────────────
    
    def save(self, path):
        self.f.write(path)
        return path
    
    def to_threejs(self):
        """Export for Three.js viewer (simplified mesh data)."""
        settings = ifcopenshell.geom.settings()
        objects = []
        for elem in self.f.by_type("IfcBuildingElementProxy"):
            try:
                shape = ifcopenshell.geom.create_shape(settings, elem)
                verts = shape.geometry.verts
                faces = shape.geometry.faces
                matrix = list(shape.transformation.matrix)
                # Get task_id from pset
                task_id = ""
                for rel in elem.IsDefinedBy or []:
                    if rel.is_a("IfcRelDefinesByProperties"):
                        pset = rel.RelatingPropertyDefinition
                        if hasattr(pset, 'HasProperties'):
                            for p in pset.HasProperties or []:
                                if p.Name == "TaskID" and p.NominalValue:
                                    task_id = str(p.NominalValue.wrappedValue)
                objects.append({
                    "guid": elem.GlobalId,
                    "name": elem.Name or "",
                    "type": elem.ObjectType or "",
                    "task_id": task_id,
                    "positions": list(verts),
                    "faces": list(faces),
                    "matrix": matrix,
                })
            except:
                pass
        return objects
    
    def generate_from_tasks(self, tasks, lat_center=32.1562, lon_center=34.8930):
        """Generate 3D model from CityOS task list."""
        count = 0
        for t in tasks:
            lat, lng = t.get("location_lat"), t.get("location_lng")
            if not lat or not lng:
                continue
            dx = (lng - lon_center) * 111320 * math.cos(lat_center * math.pi / 180)
            dy = (lat - lat_center) * 111320
            tags = " ".join(t.get("tags", []))
            priority = t.get("priority", "medium")
            scale = {"low": 2, "medium": 3, "high": 5, "critical": 7, "emergency": 8}.get(priority, 3)
            tid = str(t.get("id", ""))
            
            if any(w in tags for w in ["כביש", "דרך", "road", "street"]):
                self.add_road(t["title"], (dx-15, dy), (dx+15, dy), width=3+scale, height=0.2, task_id=tid)
            elif any(w in tags for w in ["בניין", "בנייה", "building"]):
                self.add_building(t["title"], dx, dy, w=8+scale, d=6+scale, h=3+scale, task_id=tid)
            elif any(w in tags for w in ["פארק", "גינה", "park"]):
                self.add_infra(t["title"], dx, dy, "Park", w=5+scale, d=5+scale, h=0.5, task_id=tid)
            elif any(w in tags for w in ["תאורה", "light"]):
                self.add_infra(t["title"], dx, dy, "StreetLight", w=0.3, d=0.3, h=6, task_id=tid)
            elif any(w in tags for w in ["אוטובוס", "bus", "תחבורה"]):
                self.add_infra(t["title"], dx, dy, "BusStop", w=2, d=1, h=2.5, task_id=tid)
            else:
                self.add_infra(t["title"], dx, dy, "Infrastructure", w=scale, d=scale, h=scale, task_id=tid)
            count += 1
        return count
    
    def generate_bcf(self, tasks):
        topics = []
        for t in tasks:
            guid = self.elements.get(str(t.get("id", "")), "")
            topic = BCFTopic(
                title=t.get("title", ""), description=t.get("description", ""),
                ifc_element_guid=guid,
                assigned_to=(t.get("assignees") or [{}])[0].get("name", "") if t.get("assignees") else "",
                priority=t.get("priority", "medium"),
                status="closed" if t.get("status") == "done" else "open",
            )
            topics.append(topic)
        return topics


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        b = IFCBuilder("CityOS BIM Demo - Hod HaSharon")
        b.add_road("דרך רמתיים", (-80, -40), (80, 40), width=8, task_id="1")
        b.add_building("בניין עירייה", 30, 40, w=30, d=22, h=18, task_id="2")
        b.add_infra("תחנת אוטובוס", -40, 20, "BusStop", w=3, d=2, h=3, task_id="3")
        b.add_road("רחוב הרצל", (-60, 15), (60, -15), width=5, task_id="4")
        b.add_infra("עמוד תאורה", -20, -30, "StreetLight", w=0.4, d=0.4, h=7, task_id="5")
        path = b.save("cityos_bim_demo.ifc")
        print(f"✅ IFC saved: {path}")
        print(f"   Elements: {len(list(b.f.by_type('IfcBuildingElementProxy')))}")
        
        threejs = b.to_threejs()
        print(f"   Three.js objects: {len(threejs)}")
        
        # Also export ThreeJS JSON for the frontend
        with open("cityos_bim_viewer.json", "w") as f:
            json.dump({"objects": threejs}, f)
        print(f"   Viewer JSON saved: cityos_bim_viewer.json")
