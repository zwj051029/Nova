import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock as Mock
from tuning.models import PIDGains, TuningConfig, TrialResult, ResponseMetrics, TelemetrySample
from tuning.reporting import explain, export_csv, export_html
from tuning.cloud_advisor import summary_payload, request_explanation


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.config=TuningConfig(device_name="<script>alert(1)</script>")
        self.history=[TrialResult(1,PIDGains(1,0,0),ResponseMetrics(True,score=20,steady_state_error=.1),True,True,
                                 [TelemetrySample(0,0,0,0),TelemetrySample(1,1,.9,1)])]

    def test_reports_and_cloud_redaction(self):
        self.assertIn("样本较少",explain(self.history,self.config))
        payload=summary_payload(self.history,self.config)
        self.assertNotIn("samples",payload["trials"][0])
        self.assertNotIn("device_name",payload)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            html=Path(directory)/"report.html"
            csv=Path(directory)/"samples.csv"
            export_html(html,self.history,self.config)
            export_csv(csv,self.history)
            self.assertNotIn("<script>",html.read_text(encoding="utf-8"))
            self.assertEqual(len(csv.read_text(encoding="utf-8-sig").splitlines()),3)

    def test_api_request_is_readonly_stateless_and_parsed(self):
        opener=Mock()
        response=opener.open.return_value.__enter__.return_value
        response.read.return_value=json.dumps({"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"analysis"}]}]}).encode()
        text=request_explanation(summary_payload(self.history,self.config),"test-only-key","user-model",opener)
        self.assertEqual(text,"analysis")
        request=opener.open.call_args.args[0]
        body=json.loads(request.data)
        self.assertFalse(body["store"])
        self.assertNotIn("tools",body)
        self.assertNotIn("test-only-key",request.data.decode())
        self.assertEqual(request.full_url,"https://api.openai.com/v1/responses")

    def test_api_incomplete_response_is_not_presented_as_success(self):
        opener=Mock()
        opener.open.return_value.__enter__.return_value.read.return_value=b'{"status":"incomplete"}'
        with self.assertRaises(ValueError):
            request_explanation({},"test","model",opener)
