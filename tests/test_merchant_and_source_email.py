"""Local regression tests. Synthetic alerts only; nothing here is a mailbox export."""
import copy, json, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from alert_parser import (  # noqa: E402
    KEYWORD_ORDER, WORKSHOP_NORM, charge_id, classify, gmail_alert_url,
    is_real_gmail_id, norm_merchant, parse_alert, reconcile_charges,
    source_email_link, source_email_link_for_group,
)
from patch_dashboard_source_email import (  # noqa: E402
    DashboardPatchError, SOURCE_EMAIL_URL_GROUP_EXPR, SOURCE_LINK_TEMPLATE,
    assert_patch_is_narrow, patch_is_idempotent, patch_serialized_dashboard,
    validate_gmail_link_template, validate_source_link_template, wrap_consumption_sql,
)
from deploy_personal_expenses import (  # noqa: E402
    DeployError, statement_request, statement_wait_timeout,
)

THREAD = "18f0aabbccddeeff"
MESSAGE = "18f0aabbccddee01"
COFFEE = "THE COFFE CUP NAVARRA SAN SALVADOR SV"
COFFEE_EE = "THE COFFEE CUP NAVARRA SAN SALVADOR SV"
WORKSHOP = "AUTO TALLER NAVARRA SAN SALVADOR SV"


def _charge(**overrides):
    row = {
        "charge_id": "placeholder",
        "message_id": "hist-synthetic",
        "charge_date_sv": "2026-11-06",
        "amount_usd": 7.42,
        "merchant": COFFEE,
        "merchant_norm": WORKSHOP_NORM,
        "bank": "Credicomer",
        "card_last4": "0707",
        "category": "transport",
        "movement_type": "purchase",
        "is_consumption": True,
        "currency": "USD",
        "raw_subject": "ALERTA MONETARIA",
        "ingested_at": "2026-11-06T21:39:00Z",
    }
    row.update(overrides)
    return row


def _parsed_coffee(merchant=COFFEE, message_id=MESSAGE, amount=7.42):
    norm = norm_merchant(merchant)
    return _charge(
        charge_id=charge_id("Credicomer", "0707", "2026-11-06", amount, norm),
        message_id=message_id,
        amount_usd=amount,
        merchant=merchant,
        merchant_norm=norm,
        category="restaurants",
    )


def _alert(merchant, amount="7.42", card="0707"):
    return {
        "bank": "Credicomer",
        "subject": "ALERTA MONETARIA TARJETAS",
        "body_text": (
            f"tarjeta **** **** **** {card} Monto $ {amount} "
            f"Comercio {merchant} Fecha 06/11/2026"
        ),
        "snippet": "",
        "message_id": MESSAGE,
        "received_at": "2026-11-06T21:39:00Z",
    }


def _usd(rows):
    return round(sum(r["amount_usd"] for r in rows), 2)


class MerchantFamilyTests(unittest.TestCase):
    def test_keyword_list_no_longer_treats_navarra_as_transport(self):
        transport = dict(KEYWORD_ORDER)["transport"]
        self.assertNotIn("NAVARRA", transport)
        self.assertIn("AUTO TALLER", transport)

    def test_coffee_spellings_stay_coffee_and_are_restaurants(self):
        for raw in (
            COFFEE,
            COFFEE_EE,
            "the coffe cup navarra",
            "THE COFFE  CUP NAVARRA",
            "COFFEE CUP",
            "COFFE CUP",
        ):
            norm = norm_merchant(raw)
            self.assertNotEqual(norm, WORKSHOP_NORM, raw)
            self.assertNotIn("AUTO TALLER", norm, raw)
            self.assertEqual(classify(raw), "restaurants", raw)
            self.assertEqual(classify(raw, "transport"), "restaurants", raw)
            self.assertEqual(classify(raw, "fees"), "restaurants", raw)
            self.assertIn("CUP", norm)

    def test_coffee_spelling_with_double_e_is_not_a_fee(self):
        self.assertNotEqual(classify(COFFEE_EE), "fees")
        self.assertNotEqual(classify("COFFEE BEAN"), "fees")
        self.assertEqual(classify("COFFEE BEAN"), "other")
        self.assertEqual(classify("SERVICE FEE"), "fees")
        self.assertEqual(classify("CARGO COMISION"), "fees")
        self.assertEqual(classify("OVERDRAFT FEE"), "fees")

    def test_workshop_stays_workshop(self):
        for raw in (WORKSHOP_NORM, WORKSHOP, "auto taller navarra"):
            self.assertEqual(norm_merchant(raw), WORKSHOP_NORM, raw)
            self.assertEqual(classify(raw), "transport", raw)
            self.assertEqual(classify(raw, "fees"), "transport", raw)

    def test_other_navarra_merchants_are_not_the_workshop(self):
        self.assertEqual(norm_merchant("PLAZA NAVARRA"), "PLAZA NAVARRA")
        self.assertEqual(classify("PLAZA NAVARRA"), "other")
        self.assertEqual(norm_merchant("TAXI NAVARRA"), "TAXI NAVARRA")
        self.assertEqual(classify("TAXI NAVARRA"), "transport")
        self.assertEqual(norm_merchant("FARMACIA NAVARRA"), "FARMACIA NAVARRA")
        self.assertEqual(classify("FARMACIA NAVARRA"), "health")
        self.assertNotEqual(classify("SELECTOS", "shopping"), "groceries")
        self.assertEqual(classify("UBER TRIP"), "transport")
        self.assertEqual(norm_merchant("UBER TRIP"), "UBER")
        self.assertEqual(classify("STARBUCKS"), "restaurants")

    def test_same_amount_coffee_and_workshop_get_different_charge_ids(self):
        coffee = charge_id("Credicomer", "0707", "2026-11-06", 7.42, norm_merchant(COFFEE))
        workshop = charge_id("Credicomer", "0707", "2026-11-06", 7.42, WORKSHOP_NORM)
        self.assertNotEqual(coffee, workshop)

    def test_parse_credicomer_coffee_and_workshop(self):
        coffee = parse_alert(_alert(COFFEE, "7.42"))
        self.assertEqual(coffee["charge_date_sv"], "2026-11-06")
        self.assertEqual(coffee["amount_usd"], 7.42)
        self.assertEqual(coffee["card_last4"], "0707")
        self.assertEqual(coffee["bank"], "Credicomer")
        self.assertEqual(coffee["merchant"], COFFEE)
        self.assertNotEqual(coffee["merchant_norm"], WORKSHOP_NORM)
        self.assertEqual(coffee["category"], "restaurants")
        self.assertEqual(coffee["movement_type"], "purchase")
        self.assertTrue(coffee["is_consumption"])

        spelled = parse_alert(_alert(COFFEE_EE, "4.05", card="4242"))
        self.assertEqual(spelled["category"], "restaurants")
        self.assertNotEqual(spelled["category"], "fees")
        self.assertNotEqual(spelled["merchant_norm"], WORKSHOP_NORM)

        workshop = parse_alert(_alert(WORKSHOP, "22.00", card="9999"))
        self.assertEqual(workshop["merchant_norm"], WORKSHOP_NORM)
        self.assertEqual(workshop["category"], "transport")
        self.assertNotEqual(workshop["charge_id"], coffee["charge_id"])


class ReconcileTests(unittest.TestCase):
    def test_collapsed_coffee_keeps_charge_id_and_does_not_duplicate(self):
        old_id = charge_id("Credicomer", "0707", "2026-11-06", 7.42, WORKSHOP_NORM)
        legacy = [_charge(
            charge_id=old_id,
            message_id="hist-synthetic-0742",
            merchant=WORKSHOP_NORM,
            merchant_norm=WORKSHOP_NORM,
            category="transport",
        )]
        parsed = [_parsed_coffee()]
        merged = reconcile_charges(legacy, parsed)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["charge_id"], old_id)
        self.assertEqual(merged[0]["merchant"], COFFEE)
        self.assertNotEqual(merged[0]["merchant_norm"], WORKSHOP_NORM)
        self.assertEqual(merged[0]["category"], "restaurants")
        self.assertEqual(merged[0]["message_id"], MESSAGE)
        self.assertEqual(_usd(legacy), _usd(merged))
        self.assertEqual(len({r["charge_id"] for r in merged}), len(merged))

    def test_raw_coffee_text_is_corrected_even_without_a_reparse(self):
        old_id = charge_id("Credicomer", "0707", "2026-11-06", 7.42, WORKSHOP_NORM)
        legacy = [_charge(charge_id=old_id, merchant=COFFEE, merchant_norm=WORKSHOP_NORM, category="transport")]
        merged = reconcile_charges(legacy, [])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["charge_id"], old_id)
        self.assertEqual(merged[0]["merchant_norm"], norm_merchant(COFFEE))
        self.assertEqual(merged[0]["category"], "restaurants")

    def test_rebuild_is_stable(self):
        old_id = charge_id("Credicomer", "0707", "2026-11-06", 7.42, WORKSHOP_NORM)
        workshop_id = charge_id("Promerica", "1881", "2026-11-06", 22.00, WORKSHOP_NORM)
        legacy = [
            _charge(charge_id=old_id, message_id="hist-synthetic-0742", merchant=WORKSHOP_NORM,
                    merchant_norm=WORKSHOP_NORM, category="transport"),
            _charge(charge_id=workshop_id, message_id="hist-workshop", merchant=WORKSHOP,
                    merchant_norm=WORKSHOP_NORM, category="transport", amount_usd=22.00,
                    bank="Promerica", card_last4="1881"),
            _charge(charge_id="selectos-1", message_id="hist-selectos", merchant="SELECTOS",
                    merchant_norm="SELECTOS", category="groceries", amount_usd=12.50,
                    bank="BI", card_last4="2222", charge_date_sv="2026-11-01"),
        ]
        workshop_parsed = _charge(
            charge_id=workshop_id, message_id="18f0bbccddeeff02", merchant=WORKSHOP,
            merchant_norm=WORKSHOP_NORM, category="transport", amount_usd=22.00,
            bank="Promerica", card_last4="1881",
        )
        parsed = [_parsed_coffee(), workshop_parsed]
        once = reconcile_charges(legacy, parsed)
        twice = reconcile_charges(once, parsed)
        self.assertEqual([r["charge_id"] for r in once], [r["charge_id"] for r in twice])
        self.assertEqual(len(once), len(legacy))
        self.assertEqual(_usd(once), _usd(legacy))
        coffee = next(r for r in twice if r["charge_id"] == old_id)
        workshop = next(r for r in twice if r["charge_id"] == workshop_id)
        self.assertEqual(coffee["category"], "restaurants")
        self.assertNotEqual(coffee["merchant_norm"], WORKSHOP_NORM)
        self.assertEqual(workshop["category"], "transport")
        self.assertEqual(workshop["merchant_norm"], WORKSHOP_NORM)
        self.assertEqual(workshop["merchant"], WORKSHOP)
        selectos = next(r for r in twice if r["charge_id"] == "selectos-1")
        self.assertEqual(selectos["category"], "groceries")
        self.assertTrue(all("_consumed" not in r for r in twice))

    def test_new_coffee_and_workshop_both_survive_when_there_is_no_legacy_row(self):
        coffee = _parsed_coffee(amount=7.42)
        workshop = parse_alert(_alert(WORKSHOP, "7.42", card="0707"))
        workshop["ingested_at"] = coffee["ingested_at"]
        workshop["message_id"] = "18f0bbccddeeff99"
        merged = reconcile_charges([], [coffee, workshop])
        self.assertEqual(len(merged), 2)
        self.assertEqual(len({r["charge_id"] for r in merged}), 2)
        cats = {r["category"] for r in merged}
        self.assertEqual(cats, {"restaurants", "transport"})

    def test_ambiguous_same_amount_does_not_double_count(self):
        old_id = charge_id("Credicomer", "0707", "2026-11-06", 7.42, WORKSHOP_NORM)
        legacy = [_charge(charge_id=old_id, merchant=WORKSHOP_NORM, merchant_norm=WORKSHOP_NORM)]
        workshop = parse_alert(_alert(WORKSHOP, "7.42"))
        workshop["message_id"] = "18f0bbccddeeff99"
        workshop["ingested_at"] = "2026-11-06T21:39:00Z"
        parsed = [_parsed_coffee(), workshop]
        merged = reconcile_charges(legacy, parsed)
        self.assertEqual(len(merged), 1)
        self.assertEqual(_usd(merged), 7.42)
        self.assertEqual(len({r["charge_id"] for r in merged}), 1)

    def test_surviving_non_workshop_text_is_un_collapsed(self):
        old_id = charge_id("BI", "3333", "2026-10-02", 9.0, WORKSHOP_NORM)
        legacy = [_charge(
            charge_id=old_id, merchant="FARMACIA NAVARRA", merchant_norm=WORKSHOP_NORM,
            category="transport", amount_usd=9.0, bank="BI", card_last4="3333",
            charge_date_sv="2026-10-02",
        )]
        merged = reconcile_charges(legacy, [])
        self.assertEqual(merged[0]["charge_id"], old_id)
        self.assertEqual(merged[0]["merchant_norm"], "FARMACIA NAVARRA")
        self.assertEqual(merged[0]["category"], "health")

    def test_duplicate_legacy_charge_id_keeps_one_and_distinct_ids(self):
        shared = "dup-charge"
        other = "other-charge"
        legacy = [
            _charge(charge_id=shared, amount_usd=7.42, merchant="FIRST", merchant_norm="FIRST",
                    category="other", message_id="hist-a"),
            _charge(charge_id=shared, amount_usd=99.00, merchant="SECOND", merchant_norm="SECOND",
                    category="other", message_id="hist-b"),
            _charge(charge_id=other, amount_usd=4.00, merchant="KEPT", merchant_norm="KEPT",
                    category="shopping", bank="BI", card_last4="3333", message_id="hist-c",
                    charge_date_sv="2026-10-01"),
        ]
        merged = reconcile_charges(legacy, [])
        self.assertEqual([r["charge_id"] for r in merged], [shared, other])
        self.assertEqual(merged[0]["amount_usd"], 7.42)
        self.assertEqual(merged[0]["merchant"], "FIRST")
        self.assertEqual(merged[1]["amount_usd"], 4.00)
        self.assertEqual(_usd(merged), 11.42)

    def test_duplicate_legacy_keeps_the_live_amount(self):
        shared = "dup-charge"
        legacy = [
            _charge(charge_id=shared, amount_usd=99.00, merchant="LANDING-A", merchant_norm="A",
                    category="other"),
            _charge(charge_id=shared, amount_usd=7.42, merchant="LANDING-B", merchant_norm="B",
                    category="restaurants"),
        ]
        live = [_charge(charge_id=shared, amount_usd=7.42, merchant="LANDING-B", merchant_norm="B",
                        category="restaurants")]
        merged = reconcile_charges(legacy, [], live)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["charge_id"], shared)
        self.assertEqual(merged[0]["amount_usd"], 7.42)
        self.assertEqual(merged[0]["merchant"], "LANDING-B")
        self.assertEqual(_usd(merged), 7.42)

    def test_parsed_charge_id_collisions_do_not_drop_distinct_charges(self):
        legacy = [_charge(charge_id="legacy-id", amount_usd=5.00, merchant="SELECTOS",
                          merchant_norm="SELECTOS", category="groceries", bank="BI",
                          card_last4="1111", message_id="hist-sel")]
        same_as_legacy = _charge(charge_id="legacy-id", amount_usd=5.00, merchant="SELECTOS MARKET",
                                 merchant_norm="SELECTOS", category="shopping", bank="BI",
                                 card_last4="1111", message_id="18f0aabbccddee11")
        first_new = _charge(charge_id="new-id", amount_usd=2.00, merchant="PUMA", merchant_norm="PUMA",
                            category="fuel", bank="BI", card_last4="2222", message_id="18f0aabbccddee12",
                            charge_date_sv="2026-11-02")
        second_copy = dict(first_new)
        second_copy["message_id"] = "18f0aabbccddee13"
        second_copy["amount_usd"] = 8.00
        other = _charge(charge_id="another-id", amount_usd=1.50, merchant="UBER", merchant_norm="UBER",
                        category="transport", bank="Promerica", card_last4="4444",
                        message_id="18f0aabbccddee14", charge_date_sv="2026-11-03")
        merged = reconcile_charges(legacy, [same_as_legacy, first_new, second_copy, other])
        self.assertEqual([r["charge_id"] for r in merged], ["legacy-id", "new-id", "another-id"])
        self.assertEqual(merged[0]["merchant"], "SELECTOS")
        self.assertEqual(merged[0]["category"], "groceries")
        self.assertEqual(merged[1]["amount_usd"], 2.00)
        self.assertEqual(_usd(merged), 8.50)

    def test_legacy_charge_id_wins_when_the_new_id_collides(self):
        legacy = [_charge(charge_id="kept", merchant="SELECTOS", merchant_norm="SELECTOS",
                          category="groceries", amount_usd=3, bank="BI", card_last4="1111")]
        parsed = [_charge(charge_id="kept", merchant="SELECTOS MARKET", merchant_norm="SELECTOS",
                          category="shopping", amount_usd=3, bank="BI", card_last4="1111",
                          message_id="18f0aabbccddee02")]
        merged = reconcile_charges(legacy, parsed)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["category"], "groceries")
        self.assertEqual(merged[0]["merchant"], "SELECTOS")


class GmailLinkTests(unittest.TestCase):
    def test_real_bronze_ids_encode_the_mailbox_once(self):
        label, url = source_email_link(MESSAGE, THREAD, True)
        self.assertEqual(label, "email")
        self.assertEqual(url, validate_gmail_link_template(url, THREAD))
        self.assertNotIn("@", url)
        self.assertIn("jg0592%40gmail.com", url)
        self.assertTrue(url.endswith("#all/" + THREAD))
        self.assertNotIn("%2540", url)

    def test_synthetic_and_missing_lineage_are_unavailable(self):
        self.assertFalse(is_real_gmail_id("hist-synthetic-0742"))
        self.assertFalse(is_real_gmail_id("a" * 32))
        self.assertFalse(is_real_gmail_id(""))
        self.assertIsNone(gmail_alert_url("hist-synthetic-0742"))
        self.assertEqual(source_email_link("hist-synthetic-0742", THREAD, True), ("unavailable", None))
        self.assertEqual(source_email_link(MESSAGE, "", True), ("unavailable", None))
        self.assertEqual(source_email_link(MESSAGE, THREAD, False), ("unavailable", None))

    def test_grouped_rows_do_not_pick_one_of_several_emails(self):
        one = source_email_link_for_group([(MESSAGE, THREAD, True)])
        self.assertEqual(one[0], "email")
        same = source_email_link_for_group([(MESSAGE, THREAD, True), ("18f0aabbccddee02", THREAD, True)])
        self.assertEqual(same[0], "email")
        self.assertEqual(same[1], one[1])
        mixed = source_email_link_for_group([
            (MESSAGE, THREAD, True),
            ("18f0aabbccddee02", "18f0aabbccddee03", True),
        ])
        self.assertEqual(mixed, ("unavailable", None))
        partial = source_email_link_for_group([(MESSAGE, THREAD, True), ("hist-synthetic", "", False)])
        self.assertEqual(partial, ("unavailable", None))


def _dashboard():
    return {
        "datasets": [
            {
                "name": "ds_consumption",
                "displayName": "Consumption",
                "queryLines": [
                    "SELECT *\n",
                    "FROM workspace.personal_expenses.silver_charges\n",
                ],
            },
            {
                "name": "ds_other",
                "displayName": "Other",
                "queryLines": ["SELECT 1 AS n\n"],
            },
        ],
        "pages": [{
            "name": "overview",
            "displayName": "Overview",
            "layout": [
                {
                    "widget": {
                        "name": "filter_movement",
                        "queries": [{"name": "main_query", "query": {
                            "datasetName": "ds_consumption",
                            "fields": [{"name": "movement_type", "expression": "`movement_type`"}],
                            "disaggregated": True,
                        }}],
                        "spec": {"version": 2, "widgetType": "filter-single-select"},
                    },
                    "position": {"x": 0, "y": 0, "width": 2, "height": 2},
                },
                {
                    "widget": {
                        "name": "by_category",
                        "queries": [{"name": "main_query", "query": {
                            "datasetName": "ds_consumption",
                            "fields": [
                                {"name": "category", "expression": "`category`"},
                                {"name": "usd", "expression": "SUM(`amount_usd`)"},
                            ],
                            "disaggregated": False,
                        }}],
                        "spec": {"version": 3, "widgetType": "bar", "encodings": {
                            "x": {"fieldName": "usd"}, "y": {"fieldName": "category"},
                        }},
                    },
                    "position": {"x": 0, "y": 2, "width": 3, "height": 5},
                },
                {
                    "widget": {
                        "name": "top_merchants",
                        "queries": [{"name": "main_query", "query": {
                            "datasetName": "ds_consumption",
                            "fields": [
                                {"name": "merchant_norm", "expression": "`merchant_norm`"},
                                {"name": "charge_date_sv", "expression": "`charge_date_sv`"},
                                {"name": "bank", "expression": "`bank`"},
                                {"name": "category", "expression": "`category`"},
                                {"name": "usd", "expression": "SUM(`amount_usd`)"},
                                {"name": "n", "expression": "COUNT(1)"},
                            ],
                            "filter": "`is_consumption`",
                            "disaggregated": False,
                        }}],
                        "spec": {
                            "version": 2,
                            "widgetType": "table",
                            "encodings": {"columns": [
                                {"fieldName": "merchant_norm", "displayName": "Merchant"},
                                {"fieldName": "charge_date_sv", "displayName": "Purchase date (SV)"},
                                {"fieldName": "bank", "displayName": "Bank"},
                                {"fieldName": "category", "displayName": "Category"},
                                {"fieldName": "usd", "displayName": "USD"},
                                {"fieldName": "n", "displayName": "N"},
                            ]},
                            "frame": {"showTitle": True, "title": "Top merchants (consumption)"},
                        },
                    },
                    "position": {"x": 0, "y": 8, "width": 6, "height": 6},
                },
            ],
        }],
    }


class DashboardPatchTests(unittest.TestCase):
    def test_patch_is_narrow_idempotent_and_encodes_the_link(self):
        original = _dashboard()
        untouched_filter = copy.deepcopy(original["pages"][0]["layout"][0])
        untouched_bar = copy.deepcopy(original["pages"][0]["layout"][1])
        patched, report = patch_serialized_dashboard(original)
        assert_patch_is_narrow(original, patched)
        self.assertEqual(patched["pages"][0]["layout"][0], untouched_filter)
        self.assertEqual(patched["pages"][0]["layout"][1], untouched_bar)
        self.assertEqual(patched["datasets"][1], original["datasets"][1])
        self.assertTrue(patch_is_idempotent(original))
        sql = "".join(patched["datasets"][0]["queryLines"])
        self.assertIn("-- personal_expenses_source_email", sql)
        self.assertIn("source_email_url", sql)
        self.assertIn("max_by(thread_id, ingested_at)", sql)
        self.assertIn("ORDER BY base.charge_date_sv DESC", sql)
        self.assertNotIn("@", sql)
        self.assertIn("jg0592%40gmail.com", sql)
        self.assertNotIn("source_thread_id", sql)
        self.assertEqual(report["sample_url"], gmail_alert_url(THREAD))
        widget = patched["pages"][0]["layout"][2]["widget"]
        self.assertEqual(patched["pages"][0]["layout"][2]["position"]["y"], 8)
        query = widget["queries"][0]["query"]
        # Live grid: SUM(amount_usd), COUNT(1), group by merchant/date/bank/category.
        # charge_id is added to that group so each purchase keeps its own link.
        # SUM and COUNT stay, so a one-charge group still sums to the charge amount.
        self.assertFalse(query["disaggregated"])
        self.assertEqual(query["filter"], "`is_consumption`")
        self.assertEqual(report["widget_grain"], "per_charge")
        fields = {f["name"]: f["expression"] for f in query["fields"]}
        self.assertEqual(fields["merchant_norm"], "`merchant`")
        self.assertEqual(fields["usd"], "SUM(`amount_usd`)")
        self.assertEqual(fields["n"], "COUNT(1)")
        self.assertEqual(fields["charge_id"], "`charge_id`")
        self.assertEqual(fields["source_email"], SOURCE_EMAIL_URL_GROUP_EXPR)
        self.assertNotIn("source_thread_id", fields)
        columns = widget["spec"]["encodings"]["columns"]
        charge = next(c for c in columns if c["fieldName"] == "charge_id")
        self.assertFalse(charge["visible"])
        displayed = [c["fieldName"] for c in columns if c.get("visible", True)]
        self.assertNotIn("charge_id", displayed)
        self.assertEqual(displayed[:6], [
            "merchant_norm", "charge_date_sv", "bank", "category", "usd", "n",
        ])
        source = next(c for c in columns if c["fieldName"] == "source_email")
        self.assertEqual(source["displayName"], "Source email")
        self.assertEqual(source["link"]["templatedURL"], SOURCE_LINK_TEMPLATE)
        validate_source_link_template(source["link"]["templatedURL"])
        self.assertNotIn("mail.google.com", source["link"]["templatedURL"])
        self.assertNotIn("#all/", source["link"]["templatedURL"])
        dumped = json.dumps(patched)
        self.assertIn("jg0592%40gmail.com", sql)
        self.assertIn("ELSE CAST(NULL AS STRING) END AS source_email_url", sql)
        self.assertNotIn("jg0592@gmail.com", dumped)
        self.assertNotIn("%2540", dumped)
        self.assertNotIn("#all/{{", dumped)

    def test_grouped_query_keeps_measures_and_marks_ambiguous_links(self):
        sd = _dashboard()
        sd["datasets"][0]["queryLines"] = [
            "SELECT merchant_norm, SUM(amount_usd) AS usd\n",
            "FROM workspace.personal_expenses.silver_charges\n",
            "GROUP BY merchant_norm\n",
        ]
        patched, report = patch_serialized_dashboard(sd)
        self.assertEqual(report["dataset_grain"], "grouped_no_message")
        self.assertFalse(report["date_order"])
        widget = patched["pages"][0]["layout"][2]["widget"]
        query = widget["queries"][0]["query"]
        self.assertFalse(query["disaggregated"])
        fields = {f["name"]: f["expression"] for f in query["fields"]}
        self.assertEqual(fields["usd"], "SUM(`amount_usd`)")
        self.assertEqual(fields["n"], "COUNT(1)")
        self.assertNotIn("charge_id", fields)
        self.assertEqual(fields["source_email"], SOURCE_EMAIL_URL_GROUP_EXPR)
        sql = "".join(patched["datasets"][0]["queryLines"])
        self.assertIn("CAST(NULL AS STRING) AS source_email_url", sql)
        self.assertNotIn("src_bronze", sql)
        self.assertNotIn("mail.google.com", sql)
        bar = patched["pages"][0]["layout"][1]["widget"]["queries"][0]["query"]["fields"]
        self.assertEqual(bar[1]["expression"], "SUM(`amount_usd`)")

    def test_rejects_a_raw_at_in_the_template(self):
        with self.assertRaises(DashboardPatchError):
            validate_gmail_link_template(
                "https://mail.google.com/mail/?authuser=jg0592@gmail.com#all/" + THREAD,
                THREAD,
            )

    def test_missing_lineage_is_null_and_not_a_gmail_root_link(self):
        self.assertIsNone(gmail_alert_url(None))
        self.assertIsNone(source_email_link("not-a-gmail-id", "", False)[1])
        validate_source_link_template("{{@}}")
        with self.assertRaises(DashboardPatchError):
            validate_source_link_template(
                "https://mail.google.com/mail/?authuser=jg0592%40gmail.com#all/{{source_thread_id}}"
            )
        sql, _grain = wrap_consumption_sql(
            "SELECT * FROM workspace.personal_expenses.silver_charges"
        )
        self.assertIn("ELSE CAST(NULL AS STRING) END AS source_email_url", sql)
        self.assertNotIn("concat('https://mail.google.com/mail/?authuser=jg0592%40gmail.com#all/', '')", sql)
        self.assertNotIn("#all/' )", sql)

    def test_narrow_check_catches_a_filter_edit(self):
        original = _dashboard()
        patched, _ = patch_serialized_dashboard(original)
        patched["pages"][0]["layout"][0]["widget"]["spec"]["version"] = 9
        with self.assertRaises(DashboardPatchError):
            assert_patch_is_narrow(original, patched)

    def test_column_injection_preserves_the_original_select(self):
        sql, grain = wrap_consumption_sql(
            "SELECT merchant_norm, charge_date_sv, amount_usd\n"
            "FROM workspace.personal_expenses.silver_charges\n"
            "ORDER BY charge_date_sv DESC"
        )
        self.assertEqual(grain, "detail")
        self.assertIn("charge_id", sql)
        self.assertIn("message_id", sql)
        self.assertIn("merchant_norm", sql)
        self.assertIn("ORDER BY base.charge_date_sv DESC", sql)
        self.assertEqual(sql.upper().count("ORDER BY"), 1)


class SqlWaitTimeoutTests(unittest.TestCase):
    def test_statement_wait_timeout_accepts_only_zero_or_five_through_fifty(self):
        self.assertEqual(statement_wait_timeout(0), "0s")
        self.assertEqual(statement_wait_timeout(5), "5s")
        self.assertEqual(statement_wait_timeout(50), "50s")
        for bad in (4, 51, 90, -1):
            with self.assertRaises(DeployError):
                statement_wait_timeout(bad)

    def test_statement_request_does_not_send_the_rejected_90s_timeout(self):
        body = statement_request("SELECT 1", "de62669408c45fc9")
        self.assertEqual(body["wait_timeout"], "50s")
        self.assertNotIn("90s", json.dumps(body))
        self.assertEqual(body["on_wait_timeout"], "CONTINUE")
        self.assertEqual(body["disposition"], "INLINE")
        self.assertEqual(body["format"], "JSON_ARRAY")
        self.assertEqual(body["warehouse_id"], "de62669408c45fc9")


class SourceLockTests(unittest.TestCase):
    def test_notebook_embeds_the_parser(self):
        etl = (ROOT / "scripts" / "etl_load_from_volume.py").read_text()
        parser = (ROOT / "scripts" / "alert_parser.py").read_text()
        if not parser.endswith("\n"):
            parser += "\n"
        start = etl.index("# --- alert_parser:")
        end = etl.index("# --- end alert_parser ---") + len("# --- end alert_parser ---")
        self.assertEqual(etl[start:end] + "\n", parser)
        self.assertNotIn("if r.message_id in legacy_ids", etl)
        self.assertIn("reconcile_charges", etl)

    def test_sources_do_not_collapse_every_navarra(self):
        for name in ("alert_parser.py", "etl_load_from_volume.py", "build_and_load.py"):
            text = (ROOT / "scripts" / name).read_text()
            self.assertNotIn('or "NAVARRA" in m', text, name)
        loader = (ROOT / "scripts" / "build_and_load.py").read_text()
        self.assertIn("from alert_parser import SEED, norm_merchant, classify, charge_id", loader)


if __name__ == "__main__":
    unittest.main()
