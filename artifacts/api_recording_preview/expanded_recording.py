# JASC Python API recording (API version 1)
# Run from the JASC environment; existing sheets need --project input.jasc.
from jasc_api import Session, series


def run(session):
    sheet1 = session.sheet(
        'source',
    )

    sheet2 = session.statistics(
        sheet1,
        name='statistics_y',
        operation_key='single_complete',
        primary_column='y',
        secondary_column='',
    )

    rows3 = session.result_row(
        'statistics',
        operation_key='single_complete',
        operation_scope='single',
        column_binding_mode='name',
        source_sheet='source',
        secondary_sheet='',
        requested_result_sheet='statistics_y',
        output_sheet='statistics_y',
        status='ok',
        error='',
        elapsed_seconds=0.01453449996188283,
        result_frame=sheet2.frame,
        requested_primary_column='y',
        primary_column='y',
        requested_secondary_column='',
        secondary_column='',
        requested_columns=None,
        columns=None,
    )

    sheet4 = session.statistics_plot_data(
        sheet1,
        name='source_y_normal_curve',
        kind='normal',
        column='y',
    )

    plot5 = session.plot(
        [series(x=(sheet1, ''), y=(sheet1, 'y'), plot_type='histogram', color='tab:blue', custom_label='source: y', fill_alpha=0.35, histogram_bins=30, histogram_density=True), series(x=(sheet4, 'value'), y=(sheet4, 'normal_density'), color='tab:red', custom_label='Normal curve')],
        name='Statistics: Single column > Complete report',
        settings={
            'title': 'Statistics: Single column > Complete report',
            'axes': {
                'x': {
                    'label': 'source: y',
                    'scale': 'linear',
                    'minimum': '',
                    'maximum': '',
                    'label_font_size': 0.0,
                    'tick_font_size': 0.0,
                },
                'left_y': {
                    'label': 'Density',
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

    sheet6 = session.statistics(
        sheet1,
        name='statistics_other',
        operation_key='single_complete',
        primary_column='other',
        secondary_column='',
    )

    rows7 = session.result_row(
        'statistics',
        operation_key='single_complete',
        operation_scope='single',
        column_binding_mode='name',
        source_sheet='source',
        secondary_sheet='',
        requested_result_sheet='statistics_other',
        output_sheet='statistics_other',
        status='ok',
        error='',
        elapsed_seconds=0.060733099933713675,
        result_frame=sheet6.frame,
        requested_primary_column='other',
        primary_column='other',
        requested_secondary_column='',
        secondary_column='',
        requested_columns=None,
        columns=None,
    )

    sheet8 = session.collect_rows(
        name='source_statistics_batch_summary',
        rows=[rows3, rows7],
        wide=False,
        operation='Statistics batch summary: operation=Single column > Complete report',
    )

    sheet9 = session.collect_rows(
        name='source_statistics_batch_wide_summary',
        rows=[rows3, rows7],
        wide=True,
        operation='Statistics batch wide/pivot summary',
    )

    sheet10 = session.interpolate(
        sheet1,
        name='interpolated_y',
        coordinate_columns=['x'],
        value_column='y',
        method='linear',
        fill_policy='nan',
        smoothing=0.0,
        epsilon=None,
        ranges=[(0.0, 11.0, 21)],
        mesh=False,
    )

    row11 = session.result_row(
        'interpolation',
        dialog={
            'coordinate_columns': ['x'],
            'epsilon': None,
            'fill_policy': 'nan',
            'method_key': 'linear',
            'mode': '1d',
            'query_mode': 'generated',
            'smoothing': 0.0,
            'value_column': 'y',
        },
        requested_result_sheet='interpolated_y',
        output_sheet='interpolated_y',
        status='ok',
        error='',
        elapsed_seconds=0.005186700029298663,
        coordinate_columns=['x'],
        value_column='y',
        query_columns=[],
        requested_coordinate_columns=['x'],
        requested_value_column='y',
        requested_query_columns=[],
        column_binding_mode='name',
        source_dataset=sheet1,
        source_sheet='',
        result_frame=sheet10.frame,
    )

    sheet12 = session.interpolate(
        sheet1,
        name='interpolated_other',
        coordinate_columns=['x'],
        value_column='other',
        method='linear',
        fill_policy='nan',
        smoothing=0.0,
        epsilon=None,
        ranges=[(0.0, 11.0, 21)],
        mesh=False,
    )

    row13 = session.result_row(
        'interpolation',
        dialog={
            'coordinate_columns': ['x'],
            'epsilon': None,
            'fill_policy': 'nan',
            'method_key': 'linear',
            'mode': '1d',
            'query_mode': 'generated',
            'smoothing': 0.0,
            'value_column': 'y',
        },
        requested_result_sheet='interpolated_other',
        output_sheet='interpolated_other',
        status='ok',
        error='',
        elapsed_seconds=0.002592200180515647,
        coordinate_columns=['x'],
        value_column='other',
        query_columns=[],
        requested_coordinate_columns=['x'],
        requested_value_column='other',
        requested_query_columns=[],
        column_binding_mode='name',
        source_dataset=sheet1,
        source_sheet='',
        result_frame=sheet12.frame,
    )

    sheet14 = session.collect_rows(
        name='source_interpolation_batch_summary',
        rows=[row11, row13],
        wide=False,
        operation='',
    )


if __name__ == "__main__":
    session = Session.from_cli()
    run(session)
    session.finish()
