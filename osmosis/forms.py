from django import forms


class BooleanInterpreterMixin(object):
    """ ModelForm mixin which causes boolean fields to interpret "0" and "false" values as False.
        By default, a ModelForm uses CheckboxInput as the widget for a BooleanField, and that
        expects False values to be submitted as empty.  By replacing CheckboxInput with Widget
        we allow forms.BooleanField.to_python to do the value intepretation, and thus allow "0"
        and "FaLsE" to be treated as False.
    """
    def __init__(self, *args, **kwargs):
        super(BooleanInterpreterMixin, self).__init__(*args, **kwargs)
        explicit_widgets = getattr(self.Meta, 'widgets', {})
        for field_name, field in self.fields.items():
            if (
                isinstance(field, forms.BooleanField) and
                field_name not in explicit_widgets # don't alter widgets which have been manually specified
            ):
                field.widget = forms.Widget()
