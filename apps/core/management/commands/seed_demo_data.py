"""
Generate a realistic demo dataset.

    python manage.py seed_demo_data --days 30 --reset

The data is *plausible*, not random noise: output follows a diurnal curve,
one line has a chronic defect problem, one machine breaks down more often,
and the inventory slowly drains so that low-stock warnings appear.
"""

import random
from datetime import time, timedelta

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.core.constants import (
    AlertStatus,
    ComparisonOperator,
    DataSource,
    DefectType,
    DowntimeReason,
    MachineStatus,
    Metric,
    MovementType,
    Severity,
    ThresholdScope,
)
from apps.core.models import (
    Alert,
    DowntimeEvent,
    Factory,
    InventoryItem,
    Machine,
    Product,
    ProductionLine,
    ProductionLog,
    QualityCheck,
    Shift,
    StockMovement,
    Threshold,
    UserProfile,
)

FACTORY_BLUEPRINT = [
    {
        "name": "Cairo Plant 1",
        "code": "CAI-01",
        "location": "10th of Ramadan City, Industrial Zone A",
        "city": "Cairo",
        "country": "Egypt",
        "timezone": "Africa/Cairo",
        "lines": [
            {"name": "Assembly Line A", "code": "LINE-A", "target": 900},
            {"name": "Assembly Line B", "code": "LINE-B", "target": 750},
            {"name": "Packaging Line C", "code": "LINE-C", "target": 1100},
        ],
    },
    {
        "name": "Alexandria Plant 2",
        "code": "ALX-02",
        "location": "Borg El Arab Industrial Free Zone",
        "city": "Alexandria",
        "country": "Egypt",
        "timezone": "Africa/Cairo",
        "lines": [
            {"name": "Component Line D", "code": "LINE-D", "target": 650},
            {"name": "Component Line E", "code": "LINE-E", "target": 600},
        ],
    },
]

PRODUCT_BLUEPRINT = [
    ("PRD-100", "Valve Body A-200", "Valves", "pcs", 22),
    ("PRD-110", "Valve Body A-220", "Valves", "pcs", 26),
    ("PRD-200", "Pump Housing P-45", "Pumps", "pcs", 45),
    ("PRD-300", "Motor Frame M-12", "Motors", "pcs", 60),
    ("PRD-400", "Gasket Kit G-07", "Sealing", "kit", 12),
    ("PRD-500", "Bearing Set B-31", "Bearings", "set", 9),
]

SHIFT_BLUEPRINT = [
    ("Morning shift", "M", (8, 0), (16, 0), False),
    ("Evening shift", "E", (16, 0), (0, 0), True),
    ("Night shift", "N", (0, 0), (8, 0), False),
]

# username, first name, last name, roles
# The password is shared by every demo user - see the ``--password`` option.
USERS = [
    ("admin", "Amr", "Hassan", ["Admin"]),
    ("manager", "Mona", "Fathy", ["Manager"]),
    ("supervisor", "Tarek", "Nabil", ["Supervisor"]),
    ("operator", "Sayed", "Ali", ["Operator"]),
    ("operator2", "Nour", "Emad", ["Operator"]),
]


class Command(BaseCommand):
    help = "Create demo factories, users, production data, downtime, quality and inventory."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30, help="How many days of history to create.")
        parser.add_argument("--reset", action="store_true", help="Delete existing demo data first.")
        parser.add_argument("--password", default=None, help="Password for every demo user.")
        parser.add_argument("--seed", type=int, default=20261107, help="Random seed.")

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(options["seed"])
        days = options["days"]
        password = options["password"] or "factory123"

        if options["reset"]:
            self.stdout.write("Removing existing data ...")
            Alert.objects.all().delete()
            Threshold.objects.all().delete()
            StockMovement.objects.all().delete()
            InventoryItem.objects.all().delete()
            QualityCheck.objects.all().delete()
            DowntimeEvent.objects.all().delete()
            ProductionLog.objects.all().delete()
            Machine.objects.all().delete()
            ProductionLine.objects.all().delete()
            Product.objects.all().delete()
            Shift.objects.all().delete()
            Factory.objects.all().delete()
            UserProfile.objects.all().delete()
            User.objects.filter(username__in=[u[0] for u in USERS]).delete()

        shifts = self.create_shifts()
        products = self.create_products()
        factories, lines, machines = self.create_structure()
        users = self.create_users(password)
        self.create_thresholds(factories, lines, users)
        self.create_production(days, lines, machines, shifts, products, users)
        self.create_downtime(days, machines, shifts, users)
        self.create_quality(days, lines, machines, shifts, products, users)
        self.create_inventory(days, products, users)
        self.raise_demo_alerts()

        self.stdout.write(self.style.SUCCESS("\nDemo data ready."))
        self.stdout.write("Users (password: %s):" % password)
        for username, first, last, roles in USERS:
            self.stdout.write("  %-12s %-14s roles=%s" % (username, f"{first} {last}", ",".join(roles)))
        self.stdout.write("\nStart the server with:  python manage.py runserver")

    # ------------------------------------------------------------------ setup
    def create_shifts(self):
        shifts = []
        for name, code, start, end, midnight in SHIFT_BLUEPRINT:
            shift, _ = Shift.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "start_time": time(start[0], start[1]),
                    "end_time": time(end[0], end[1]),
                    "crosses_midnight": midnight,
                },
            )
            shifts.append(shift)
        return shifts

    def create_products(self):
        products = []
        for code, name, category, unit, cycle in PRODUCT_BLUEPRINT:
            product, _ = Product.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": category,
                    "unit": unit,
                    "ideal_cycle_time_seconds": cycle,
                    "standard_daily_qty": 800,
                },
            )
            products.append(product)
        return products

    def create_structure(self):
        factories, lines, machines = [], [], []
        for blueprint in FACTORY_BLUEPRINT:
            factory, _ = Factory.objects.get_or_create(
                code=blueprint["code"],
                defaults={
                    "name": blueprint["name"],
                    "location": blueprint["location"],
                    "city": blueprint["city"],
                    "country": blueprint["country"],
                    "timezone": blueprint["timezone"],
                },
            )
            factories.append(factory)
            for index, line_blueprint in enumerate(blueprint["lines"]):
                line, _ = ProductionLine.objects.get_or_create(
                    factory=factory,
                    code=line_blueprint["code"],
                    defaults={
                        "name": line_blueprint["name"],
                        "target_daily_qty": line_blueprint["target"],
                        "sort_order": index,
                    },
                )
                lines.append(line)
                for machine_index in range(3):
                    machine_code = f"{line_blueprint['code']}-M{machine_index + 1:02d}"
                    machine, _ = Machine.objects.get_or_create(
                        production_line=line,
                        code=machine_code,
                        defaults={
                            "name": f"{line_blueprint['name']} machine {machine_index + 1}",
                            "manufacturer": random.choice(["Siemens", "Fanuc", "ABB", "Kuka"]),
                            "model_name": f"LineMate {random.randint(200, 900)}",
                            "status": MachineStatus.IDLE,
                        },
                    )
                    machines.append(machine)
        return factories, lines, machines

    def create_users(self, password):
        from apps.core.permissions import ensure_groups

        ensure_groups()
        users = {}
        for username, first, last, roles in USERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"first_name": first, "last_name": last, "email": f"{username}@example.com"},
            )
            if created:
                user.set_password(password)
                user.save()
            # The Admin account also runs the Django admin site, which needs
            # staff rights on top of the Admin group.
            if username == "admin" and not (user.is_superuser and user.is_staff):
                user.is_superuser = True
                user.is_staff = True
                user.save(update_fields=["is_superuser", "is_staff"])
            user.groups.set([Group.objects.get(name=role) for role in roles])
            users[username] = user

        # Scope the supervisor and one operator to a single line.
        line = ProductionLine.objects.filter(code="LINE-A").first()
        shift = Shift.objects.filter(code="M").first()
        if line:
            UserProfile.objects.update_or_create(
                user=users["supervisor"],
                defaults={"production_line": line, "shift": shift, "job_title": "Line supervisor"},
            )
            UserProfile.objects.update_or_create(
                user=users["operator"],
                defaults={"production_line": line, "shift": shift, "job_title": "Line operator"},
            )
        return users

    def create_thresholds(self, factories, lines, users):
        defaults = [
            {
                "name": "Defect rate above 3%",
                "description": "Raise a warning when the defect rate of a line exceeds 3%.",
                "scope_type": ThresholdScope.LINE,
                "metric": Metric.DEFECT_RATE,
                "operator": ComparisonOperator.GT,
                "value": 3,
                "severity": Severity.WARNING,
                "cooldown_minutes": 60,
            },
            {
                "name": "OEE below 65%",
                "description": "Overall equipment effectiveness below the target.",
                "scope_type": ThresholdScope.FACTORY,
                "factory": factories[0] if factories else None,
                "metric": Metric.OEE,
                "operator": ComparisonOperator.LT,
                "value": 65,
                "severity": Severity.WARNING,
                "cooldown_minutes": 60,
            },
            {
                "name": "Line stopped for more than 15 minutes",
                "description": "A line that stays down for a quarter of an hour.",
                "scope_type": ThresholdScope.GLOBAL,
                "metric": Metric.LINE_STOPPED_MINUTES,
                "operator": ComparisonOperator.GT,
                "value": 15,
                "severity": Severity.CRITICAL,
                "cooldown_minutes": 15,
            },
            {
                "name": "Daily downtime above 120 minutes",
                "description": "Too much lost time in one day.",
                "scope_type": ThresholdScope.GLOBAL,
                "metric": Metric.DOWNTIME_MINUTES,
                "operator": ComparisonOperator.GT,
                "value": 120,
                "severity": Severity.WARNING,
                "cooldown_minutes": 120,
            },
            {
                "name": "Low stock items",
                "description": "Any item at or below its reorder point.",
                "scope_type": ThresholdScope.GLOBAL,
                "metric": Metric.LOW_STOCK,
                "operator": ComparisonOperator.GT,
                "value": 0,
                "severity": Severity.INFO,
                "cooldown_minutes": 240,
            },
            {
                "name": "Output below 80% of target",
                "description": "The plant is not reaching its plan.",
                "scope_type": ThresholdScope.LINE,
                "metric": Metric.OUTPUT_ATTACHMENT,
                "operator": ComparisonOperator.LT,
                "value": 80,
                "severity": Severity.CRITICAL,
                "cooldown_minutes": 60,
            },
        ]
        for spec in defaults:
            threshold, created = Threshold.objects.get_or_create(
                name=spec["name"], defaults=spec
            )
            if created:
                threshold.recipients.set([users["manager"], users["admin"]])

    # ----------------------------------------------------------------- events
    def create_production(self, days, lines, machines, shifts, products, users):
        today = timezone.localdate()
        logs = []
        operator = users.get("operator")
        supervisor = users.get("supervisor")

        for day_offset in range(days, -1, -1):
            day = today - timedelta(days=day_offset)
            is_weekend = day.weekday() >= 5
            for line_index, line in enumerate(lines):
                line_machines = [m for m in machines if m.production_line_id == line.id]
                for shift in shifts:
                    product = random.choice(products)
                    base = max(line.target_daily_qty / 3, 10)
                    if is_weekend:
                        base *= 0.55
                    for hour in range(24):
                        # Only the hours that belong to this shift produce.
                        if not self._hour_in_shift(hour, shift):
                            continue
                        # Diurnal curve: slower at night, peak in the morning.
                        factor = self._hour_factor(hour)
                        noise = random.uniform(0.82, 1.12)
                        produced = int(base * factor * noise / 12)
                        target = int(base * factor / 12)
                        if produced <= 0:
                            continue

                        # LINE-B has a chronic quality problem.
                        defect_rate = random.uniform(0.004, 0.022)
                        if line.code == "LINE-B":
                            defect_rate = random.uniform(0.025, 0.075)
                        defect = int(produced * defect_rate)
                        good = produced - defect
                        machine = random.choice(line_machines) if line_machines else None
                        logs.append(
                            ProductionLog(
                                production_line=line,
                                machine=machine,
                                shift=shift,
                                product=product,
                                date=day,
                                hour=hour,
                                qty_produced=produced,
                                qty_good=good,
                                qty_defect=defect,
                                target_qty=target,
                                recorded_at=timezone.make_aware(
                                    timezone.datetime.combine(day, timezone.datetime.min.time())
                                )
                                + timedelta(hours=hour),
                                source=random.choice(
                                    [DataSource.MANUAL, DataSource.MANUAL, DataSource.API, DataSource.IMPORT]
                                ),
                                recorded_by=operator if line_index % 2 else supervisor,
                            )
                        )
        ProductionLog.objects.bulk_create(logs, batch_size=1000)
        self.stdout.write(f"  production logs : {len(logs)}")

    def create_downtime(self, days, machines, shifts, users):
        today = timezone.localdate()
        events = []
        reasons = [
            (DowntimeReason.MECHANICAL, 28),
            (DowntimeReason.ELECTRICAL, 18),
            (DowntimeReason.MATERIAL, 20),
            (DowntimeReason.MANPOWER, 12),
            (DowntimeReason.PROCESS, 12),
            (DowntimeReason.PLANNED, 6),
            (DowntimeReason.QUALITY, 3),
            (DowntimeReason.OTHER, 1),
        ]
        reason_pool = []
        for reason, weight in reasons:
            reason_pool.extend([reason] * weight)

        for day_offset in range(days, -1, -1):
            day = today - timedelta(days=day_offset)
            for machine in machines:
                # LINE-B-M02 is the problem child.
                breakdown_chance = 0.45 if machine.code == "LINE-B-M02" else 0.22
                for _ in range(random.randint(0, 3)):
                    if random.random() > breakdown_chance:
                        continue
                    hour = random.randint(0, 23)
                    started = timezone.make_aware(
                        timezone.datetime.combine(day, timezone.datetime.min.time())
                    ) + timedelta(hours=hour, minutes=random.choice([0, 5, 10, 15, 20, 25, 30, 40, 50]))
                    duration = random.choice(
                        [5, 10, 12, 15, 20, 25, 30, 35, 45, 60, 75, 90, 120]
                    )
                    reason = random.choice(reason_pool)
                    events.append(
                        DowntimeEvent(
                            machine=machine,
                            production_line=machine.production_line,
                            shift=Shift.for_datetime(started),
                            started_at=started,
                            ended_at=started + timedelta(minutes=duration),
                            duration_minutes=duration,
                            reason_category=reason,
                            reason_code=random.choice(
                                ["BEARING", "BELT", "SENSOR", "FEEDER", "OPERATOR", "CHANGEOVER", "TOOL"]
                            )
                            if reason != DowntimeReason.PLANNED
                            else "PM",
                            reason_note="",
                            source=random.choice([DataSource.MANUAL, DataSource.API]),
                            recorded_by=users.get("supervisor"),
                        )
                    )

        # One machine that is still broken right now.
        broken_machine = next((m for m in machines if m.code == "LINE-B-M02"), machines[0])
        started = timezone.now() - timedelta(minutes=random.randint(20, 55))
        events.append(
            DowntimeEvent(
                machine=broken_machine,
                production_line=broken_machine.production_line,
                shift=Shift.for_datetime(started),
                started_at=started,
                ended_at=None,
                duration_minutes=int((timezone.now() - started).total_seconds() // 60),
                reason_category=DowntimeReason.MECHANICAL,
                reason_code="BEARING",
                reason_note="Bearing temperature too high - maintenance on the way",
                source=DataSource.MANUAL,
                recorded_by=users.get("supervisor"),
            )
        )
        DowntimeEvent.objects.bulk_create(events, batch_size=500)
        self.stdout.write(f"  downtime events : {len(events)}")

    def create_quality(self, days, lines, machines, shifts, products, users):
        today = timezone.localdate()
        checks = []
        defect_types = list(DefectType.values)
        for day_offset in range(days, -1, -1):
            day = today - timedelta(days=day_offset)
            for line in lines:
                line_machines = [m for m in machines if m.production_line_id == line.id]
                for shift in shifts:
                    if random.random() > 0.55:
                        continue
                    product = random.choice(products)
                    checked = random.choice([20, 25, 30, 40, 50])
                    defect_rate = random.uniform(0.01, 0.045)
                    if line.code == "LINE-B":
                        defect_rate = random.uniform(0.04, 0.11)
                    defected = max(int(checked * defect_rate), 0)
                    hour = random.randint(0, 23)
                    checks.append(
                        QualityCheck(
                            production_line=line,
                            machine=random.choice(line_machines) if line_machines else None,
                            product=product,
                            shift=shift,
                            checked_at=timezone.make_aware(
                                timezone.datetime.combine(day, timezone.datetime.min.time())
                            ) + timedelta(hours=hour, minutes=random.randint(0, 59)),
                            qty_checked=checked,
                            qty_passed=checked - defected,
                            qty_defected=defected,
                            defect_type=random.choice(defect_types),
                            defect_count=defected,
                            inspector=users.get("operator"),
                            source=DataSource.MANUAL,
                        )
                    )
        QualityCheck.objects.bulk_create(checks, batch_size=500)
        self.stdout.write(f"  quality checks  : {len(checks)}")

    def create_inventory(self, days, products, users):
        today = timezone.localdate()
        items = []
        movements = []
        warehouses = [("WH-01", "Main warehouse"), ("WH-02", "Line side store")]
        for product in products:
            for warehouse_code, warehouse_name in warehouses:
                reorder_point = random.choice([150, 200, 300, 450])
                quantity = reorder_point + random.randint(20, 700)
                item = InventoryItem.objects.create(
                    product=product,
                    warehouse_code=warehouse_code,
                    warehouse_name=warehouse_name,
                    qty_on_hand=quantity,
                    qty_reserved=random.randint(0, 40),
                    reorder_point=reorder_point,
                    reorder_qty=reorder_point * 2,
                    unit_cost=round(random.uniform(12, 480), 2),
                )
                items.append(item)

                for day_offset in range(days, -1, -1):
                    if random.random() > 0.35:
                        continue
                    day = today - timedelta(days=day_offset)
                    movement_type = random.choice(
                        [MovementType.IN, MovementType.OUT, MovementType.OUT, MovementType.ADJUST]
                    )
                    amount = random.randint(5, 120)
                    if movement_type == MovementType.OUT:
                        quantity = max(quantity - amount, 0)
                    elif movement_type == MovementType.IN:
                        quantity += amount
                    movements.append(
                        StockMovement(
                            inventory_item=item,
                            movement_type=movement_type,
                            quantity=amount,
                            balance_after=quantity,
                            reference_no=f"REF-{random.randint(10000, 99999)}",
                            reason=random.choice(
                                ["Purchase receipt", "Line consumption", "Cycle count", "Return"]
                            ),
                            moved_at=timezone.make_aware(
                                timezone.datetime.combine(day, timezone.datetime.min.time())
                            )
                            + timedelta(hours=random.randint(6, 18), minutes=random.randint(0, 59)),
                            recorded_by=users.get("manager"),
                            source=DataSource.MANUAL,
                        )
                    )
        StockMovement.objects.bulk_create(movements, batch_size=500)
        # Make sure the stored balance matches the last movement.
        for item in items:
            last = StockMovement.objects.filter(inventory_item=item).order_by("-moved_at").first()
            if last:
                item.qty_on_hand = last.balance_after
                item.save(update_fields=["qty_on_hand"])
        self.stdout.write(f"  inventory items : {len(items)}")
        self.stdout.write(f"  stock movements : {len(movements)}")

    # ---------------------------------------------------------------- helpers
    def raise_demo_alerts(self):
        """Run the threshold engine once so the demo shows real alerts."""
        from apps.core.services.alerts import evaluate_thresholds

        created = evaluate_thresholds(send_email=False)
        self.stdout.write(f"  alerts raised   : {len(created)}")

    @staticmethod
    def _hour_in_shift(hour, shift):
        start = shift.start_time.hour
        end = shift.end_time.hour
        if end <= start:
            return hour >= start or hour < end
        return start <= hour < end

    @staticmethod
    def _hour_factor(hour):
        """Output multiplier per hour of the day."""
        if 6 <= hour < 10:
            return 1.18
        if 10 <= hour < 12:
            return 1.05
        if 12 <= hour < 14:
            return 0.78
        if 14 <= hour < 18:
            return 1.08
        if 18 <= hour < 22:
            return 0.95
        if 22 <= hour or hour < 5:
            return 0.72
        return 0.88
