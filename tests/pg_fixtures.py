"""Fixtures of the Procedure Generator tests (not a test module): a generated PDF 'manual', a PNG and a JPEG, mock model answers, a mock Anthropic client.
Nothing here touches the network; every PDF is written by reportlab in the test."""
import io
from pathlib import Path
from types import SimpleNamespace


def make_pdf(path, pages=4, title='Test Meter 100 Performance Verification'):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=letter)
    for n in range(1, pages + 1):
        c.setFont('Helvetica-Bold', 14)
        c.drawString(72, 740, f'{title}  -  page {n}')
        c.setFont('Helvetica', 10)
        y = 700
        for i, line in enumerate(('Step  Function   Range    Input      Low        High', f'{n}-1   DC volts   10 V     5.000 V    4.995      5.005',
                                  f'{n}-2   DC volts   100 mV   50.00 mV   49.95      50.05', f'{n}-3   AC volts   10 V     1.000 V   1 kHz  0.990  1.010')):
            c.drawString(72, y - 18 * i, line)
        c.showPage()
    c.save()
    return Path(path)


def make_png(path, size=(64, 48)):
    from PIL import Image
    Image.new('RGB', size, (200, 220, 240)).save(path, format='PNG')
    return Path(path)


def make_jpg(path, size=(64, 48)):
    from PIL import Image
    Image.new('RGB', size, (240, 220, 200)).save(path, format='JPEG')
    return Path(path)


def model_item(image=1, step='', kind='DCV', section='DC volts', range='', nominal='', low='', high='', frequency='', level='', accuracy='', tc='', uncertain=False, note=''):
    return dict(image=image, step=step, function_kind=kind, section=section, range=range, nominal=nominal, frequency=frequency, level=level, low_limit=low, high_limit=high,
                accuracy=accuracy, tc_type=tc, uncertain=uncertain, confidence_note=note)


def good_items():
    """What a perfect reading of fixture page 1 returns (all on image 1)."""
    return [model_item(1, '1-1', 'DCV', 'DC volts', '10 V', '5.000 V', '4.995 V', '5.005 V'),
            model_item(1, '1-2', 'DCV', 'DC volts', '100 mV', '50.00 mV', '49.95 mV', '50.05 mV'),
            model_item(1, '1-3', 'ACV', 'AC volts', '10 V', '1.000 V', '0.990 V', '1.010 V', frequency='1 kHz')]


class FakeUsage:
    input_tokens = 1234
    output_tokens = 321


class FakeResponse:
    def __init__(self, rows, stop_reason='tool_use', notes=''):
        self.content = [SimpleNamespace(type='text', text='ok'), SimpleNamespace(type='tool_use', name='report_table_rows', id='tu_1', input={'rows': rows, 'page_notes': notes})]
        self.stop_reason = stop_reason
        self.usage = FakeUsage()


class FakeClient:
    """A stand-in for anthropic.Anthropic: records every request body; `script` = list of exceptions / responses returned in order."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item
