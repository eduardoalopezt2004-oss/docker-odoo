from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFleetInspection(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super(TestFleetInspection, cls).setUpClass()
        brand = cls.env["fleet.vehicle.model.brand"].create({"name": "Marca de prueba"})
        model = cls.env["fleet.vehicle.model"].create({"name": "Modelo de prueba", "brand_id": brand.id})
        cls.vehicle = cls.env["fleet.vehicle"].create({"model_id": model.id, "license_plate": "AB123CD"})
        cls.inspector = cls.env["res.users"].create({
            "name": "Inspector de prueba",
            "login": "inspector_test",
            "groups_id": [(6, 0, [cls.env.ref("fleet_inspection.group_fleet_inspection_user").id])],
        })
        cls.other_inspector = cls.env["res.users"].create({
            "name": "Otro inspector",
            "login": "other_inspector_test",
            "groups_id": [(6, 0, [cls.env.ref("fleet_inspection.group_fleet_inspection_user").id])],
        })

    def _new_inspection(self, **vals):
        values = {"vehicle_id": self.vehicle.id, "vehicle_type": "truck", "inspector_id": self.inspector.id}
        values.update(vals)
        return self.env["fleet.inspection"].create(values)

    def test_create_loads_checklist_and_sequence(self):
        inspection = self._new_inspection()
        self.assertTrue(inspection.name.startswith("INS/"))
        items = self.env["fleet.inspection.item"].search([])
        self.assertEqual(inspection.line_ids.mapped("item_id"), items)

    def test_display_name_includes_plate(self):
        inspection = self._new_inspection()
        self.assertIn("AB123CD", inspection.display_name)

    def test_display_name_same_format_as_name_get(self):
        """El texto es el mismo que daba name_get en la 16: número - placa, o número - nombre."""
        inspection = self._new_inspection()
        self.assertEqual(inspection.display_name, "%s - AB123CD" % inspection.name)
        self.vehicle.license_plate = False
        self.assertEqual(inspection.display_name, "%s - %s" % (inspection.name, self.vehicle.name))

    def test_vehicle_editable_only_in_draft(self):
        """En la 16 lo hacía states= en el campo; en la 18 lo hace el formulario."""
        inspection = self._new_inspection()
        form = Form(inspection)
        form.vehicle_type = "car"
        form.save()
        self.assertEqual(inspection.vehicle_type, "car")
        inspection.action_start()
        form = Form(inspection)
        with self.assertRaises(AssertionError):
            form.vehicle_type = "truck"
        with self.assertRaises(AssertionError):
            form.vehicle_id = self.vehicle

    def test_full_flow_approved(self):
        inspection = self._new_inspection()
        inspection.action_start()
        self.assertEqual(inspection.state, "in_progress")
        with self.assertRaises(UserError):
            inspection.action_approve()
        inspection.line_ids.write({"result": "ok"})
        inspection.action_approve()
        self.assertEqual(inspection.state, "approved")

    def test_critical_failure_blocks_approval(self):
        inspection = self._new_inspection()
        inspection.action_start()
        inspection.line_ids.write({"result": "ok"})
        brakes = inspection.line_ids.filtered(lambda l: l.item_id == self.env.ref("fleet_inspection.item_brakes"))
        brakes.result = "fail"
        self.assertEqual(inspection.failed_count, 1)
        with self.assertRaises(UserError):
            inspection.action_approve()
        inspection.action_reject()
        self.assertEqual(inspection.state, "rejected")

    def test_negative_odometer(self):
        with self.assertRaises(ValidationError):
            self._new_inspection(odometer=-10)

    def test_inspector_sees_only_own(self):
        own = self._new_inspection()
        other = self._new_inspection(inspector_id=self.other_inspector.id)
        visible = self.env["fleet.inspection"].with_user(self.inspector).search([])
        self.assertIn(own, visible)
        self.assertNotIn(other, visible)

    def test_inspector_cannot_delete(self):
        inspection = self._new_inspection()
        with self.assertRaises(AccessError):
            inspection.with_user(self.inspector).unlink()

    def test_form_default_inspector(self):
        form = Form(self.env["fleet.inspection"].with_user(self.inspector))
        form.vehicle_id = self.vehicle
        inspection = form.save()
        self.assertEqual(inspection.inspector_id, self.inspector)
        self.assertEqual(inspection.vehicle_type, "car")

    def test_cron_marks_overdue_once(self):
        inspection = self._new_inspection(date=fields.Date.today() - timedelta(days=10))
        inspection.action_start()
        self.env["fleet.inspection"]._cron_mark_overdue()
        self.env["fleet.inspection"]._cron_mark_overdue()
        self.assertTrue(inspection.is_overdue)
        self.assertEqual(len(inspection.activity_ids), 1)
