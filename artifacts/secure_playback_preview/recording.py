# JASC Python API recording (API version 1)
# Replay through JASC or python -m jasc_api; existing sheets need --project input.jasc.
from jasc_api import Session, series, launch_recording


def run(session):
    sheet1 = session.sheet(
        'source',
    )

    session.smooth(
        sheet1,
        x_column='x',
        y_column='y',
        method='savgol',
        output_column='y_smoothed',
        window_length=11,
        polynomial_order=3,
        lowess_fraction=0.15,
        lowess_iterations=2,
        fft_cutoff_fraction=0.1,
        derivative_smoothing_method='savgol',
        derivative_median_window=1,
        preserve_endpoints=True,
    )

    plot3 = session.plot(
        [series(x=(sheet1, 'x'), y=(sheet1, 'y'), color='0.55', custom_label='y'), series(x=(sheet1, 'x'), y=(sheet1, 'y_smoothed'), color='tab:red', custom_label='y_smoothed')],
        name='Savitzky-Golay: y',
        settings={
            'title': 'Savitzky-Golay: y',
            'axes': {
                'x': {
                    'label': '',
                    'scale': 'linear',
                    'minimum': '',
                    'maximum': '',
                    'label_font_size': 0.0,
                    'tick_font_size': 0.0,
                },
                'left_y': {
                    'label': '',
                    'scale': 'linear',
                    'minimum': '',
                    'maximum': '',
                    'label_font_size': 0.0,
                    'tick_font_size': 0.0,
                },
                'right_y': {
                    'label': '',
                    'scale': 'linear',
                    'minimum': '',
                    'maximum': '',
                    'label_font_size': 0.0,
                    'tick_font_size': 0.0,
                },
            },
            'grid': {
                'enabled': True,
            },
            'legend': {
                'enabled': True,
                'location': 'best',
                'font_size': 10.0,
                'title': '',
                'title_font_size': 10.0,
                'columns': 1,
                'frame_enabled': True,
                'frame_alpha': 0.8,
                'marker_scale': 1.0,
                'handle_length': 2.0,
                'include_locators': True,
                'include_confidence_bands': True,
            },
            'figure': {
                'width': 7.0,
                'height': 4.8,
                'size_mode': 'figure',
            },
            'style': {
                'preset': '',
                'cycle': '',
                'use_latex': False,
                'custom': '',
            },
        },
        locators=[],
    )

    fit4 = session.fit(
        sheet1,
        x_column='x',
        y_column='y_smoothed',
        x_weight_column=None,
        weight_column=None,
        curve_name='source_fit',
        residual_name='source_residuals',
        create_residuals=True,
        model_key='linear',
        method='trf',
        initial_parameters=[1.0, 0.0],
        lower_bounds=[None, None],
        upper_bounds=[None, None],
        fixed_parameters=[False, False],
        weight_mode='sigma',
        absolute_sigma=False,
        include_confidence_band=True,
        confidence_level=0.95,
        fit_points=400,
        custom_models=[],
        x_bounds=None,
        y_bounds=None,
    )

    plot7 = session.plot(
        [series(x=(sheet1, 'x'), y=(sheet1, 'y_smoothed'), plot_type='scatter', color='tab:blue', line_style='', marker='o', custom_label='source: y_smoothed'), series(x=(fit4.curve, 'fit_x'), y=(fit4.curve, 'fit_y'), color='tab:red', custom_label='Linear fit', lower_column='fit_lower', upper_column='fit_upper'), series(x=(fit4.residuals, 'x'), y=(fit4.residuals, 'residual'), plot_type='scatter', color='tab:green', line_style='', marker='.', y_axis='right', custom_label='Residuals')],
        name='Linear fit',
        settings={
            'title': 'Linear fit',
            'axes': {
                'x': {
                    'label': 'x',
                    'scale': 'linear',
                    'minimum': '',
                    'maximum': '',
                    'label_font_size': 0.0,
                    'tick_font_size': 0.0,
                },
                'left_y': {
                    'label': 'Smoothed y',
                    'scale': 'linear',
                    'minimum': '',
                    'maximum': '',
                    'label_font_size': 0.0,
                    'tick_font_size': 0.0,
                },
                'right_y': {
                    'label': 'Residual',
                    'scale': 'linear',
                    'minimum': '',
                    'maximum': '',
                    'label_font_size': 0.0,
                    'tick_font_size': 0.0,
                },
            },
            'grid': {
                'enabled': True,
            },
            'legend': {
                'enabled': True,
                'location': 'best',
                'font_size': 10.0,
                'title': '',
                'title_font_size': 10.0,
                'columns': 1,
                'frame_enabled': True,
                'frame_alpha': 0.8,
                'marker_scale': 1.0,
                'handle_length': 2.0,
                'include_locators': True,
                'include_confidence_bands': True,
            },
            'figure': {
                'width': 7.0,
                'height': 4.8,
                'size_mode': 'figure',
            },
            'style': {
                'preset': '',
                'cycle': '',
                'use_latex': False,
                'custom': '',
            },
        },
        locators=[],
    )


if __name__ == "__main__":
    launch_recording(__file__)
