# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
from mplsoccer import Sbopen

# Estilo visual
plt.rcParams.update({
    'font.family': 'DejaVu Sans',
    'axes.edgecolor': '#CCCCCC',
    'axes.linewidth': 0.8,
    'axes.labelcolor': '#222222',
    'xtick.color': '#444444',
    'ytick.color': '#444444',
    'figure.facecolor': 'white',
    'axes.facecolor': '#FAFAFA',
    'axes.titleweight': 'bold',
    'axes.titlesize': 18,
    'axes.labelsize': 13,
    'xtick.labelsize': 11,
    'ytick.labelsize': 11
})

# Carga de datos
parser = Sbopen(dataframe=True)
COMP_ID = 223
SEASON_ID = 282
matches = parser.match(COMP_ID, SEASON_ID)

all_events = []
player_minutes, player_context_minutes, player_team = {}, {}, {}

# Procesamiento de eventos
for match_id in matches['match_id']:
    events, _, _, _ = parser.event(match_id)
    if events.empty:
        continue
    events = events.sort_values(['period', 'minute', 'second']).reset_index(drop=True)
    home = matches.loc[matches['match_id'] == match_id, 'home_team_name'].values[0]
    away = matches.loc[matches['match_id'] == match_id, 'away_team_name'].values[0]
    home_goals = away_goals = 0
    events['home_score'] = events['away_score'] = 0

    for idx, row in events.iterrows():
        if row['type_name'] == 'Goal':
            if row['team_name'] == home:
                home_goals += 1
            else:
                away_goals += 1
        events.at[idx, 'home_score'] = home_goals
        events.at[idx, 'away_score'] = away_goals

    def get_state(row):
        if row['possession_team_name'] == home:
            return 'Winning' if row['home_score'] > row['away_score'] else \
                   'Drawing' if row['home_score'] == row['away_score'] else 'Losing'
        else:
            return 'Winning' if row['away_score'] > row['home_score'] else \
                   'Drawing' if row['away_score'] == row['home_score'] else 'Losing'

    events['match_state'] = events.apply(get_state, axis=1)
    events['match_id'] = match_id
    all_events.append(events)

    for player, group in events.groupby('player_name'):
        player_minutes[player] = player_minutes.get(player, 0) + group['minute'].max()
        player_team[player] = player_team.get(player, group['team_name'].iloc[0])
        player_context_minutes[player] = player_context_minutes.get(player, 0) + \
            group[group['match_state'].isin(['Drawing', 'Losing'])]['minute'].nunique()

# Consolidación
all_df = pd.concat(all_events)
mid_keywords = ['Midfield', 'midfield']
midfielders = all_df[all_df['position_name'].notnull() & 
                     all_df['position_name'].str.contains('|'.join(mid_keywords))]['player_name'].unique()

# Danger passes
danger_passes = []
for match_id in all_df['match_id'].unique():
    df = all_df[all_df['match_id'] == match_id]
    for period in [1, 2]:
        passes = df[(df['type_name'] == 'Pass') & (df['outcome_name'].isnull()) &
                    (df['sub_type_name'].isnull()) & (df['period'] == period) &
                    (df['match_state'].isin(['Drawing', 'Losing']))].copy()
        shots = df[(df['type_name'] == 'Shot') & (df['period'] == period) &
                   (df['match_state'].isin(['Drawing', 'Losing'])) &
                   (df['shot_statsbomb_xg'] >= 0.07)][['minute', 'second']]
        if shots.empty or passes.empty:
            continue
        shot_times = shots['minute'] * 60 + shots['second']
        shot_start = shot_times - 15
        shot_start = shot_start.apply(lambda x: x if x > 0 else (period - 1) * 45)
        pass_times = passes['minute'] * 60 + passes['second']
        passes['is_danger'] = pass_times.apply(lambda x: any((shot_start < x) & (x < shot_times)))
        danger_passes.append(passes[passes['is_danger']])

# Interceptions y conteos
interceptions = all_df[(all_df['type_name'] == 'Interception') &
                       (all_df['match_state'].isin(['Drawing', 'Losing']))]
passes_df = pd.concat(danger_passes, ignore_index=True)
passes_count = passes_df.groupby('player_name').size().reset_index(name='danger_passes')
interceptions_count = interceptions.groupby('player_name').size().reset_index(name='interceptions')

# Dataframe principal
minutes_df = pd.DataFrame({
    'player_name': list(player_minutes.keys()),
    'minutes_total': list(player_minutes.values()),
    'minutes_context': [player_context_minutes[p] for p in player_minutes.keys()],
    'team': [player_team[p] for p in player_minutes.keys()]
})

df = minutes_df.merge(passes_count, on='player_name', how='left')\
               .merge(interceptions_count, on='player_name', how='left')
df.fillna(0, inplace=True)
df = df[(df['minutes_total'] >= 40) & 
        (df['danger_passes'] > 0) & 
        (df['interceptions'] > 0) & 
        (df['player_name'].isin(midfielders))].copy()

# KPI ponderado
df['dp_per90'] = df['danger_passes'] / (df['minutes_total'] / 90)
df['int_per90'] = df['interceptions'] / (df['minutes_total'] / 90)
df['kpi'] = df['dp_per90'] * 1.2 + df['int_per90']
df['kpi_weighted'] = df['kpi'] * np.sqrt(df['minutes_total'] / 90)
df['team_code'] = df['team'].str[:3].str.upper()
df['is_valverde'] = df['player_name'].str.contains('Valverde', case=False)

# Tamaño normalizado
min_size = 40
max_size = 400
df['circle_size'] = ((df['kpi_weighted'] - df['kpi_weighted'].min()) /
                     (df['kpi_weighted'].max() - df['kpi_weighted'].min())) * (max_size - min_size) + min_size

# Top 5%
threshold = df['kpi_weighted'].quantile(0.95)
df['is_top5'] = df['kpi_weighted'] >= threshold


# === SCATTER FINAL ===
fig, ax = plt.subplots(figsize=(14, 7))

celeste_uru = '#78B7E5'

# Puntos principales
for _, row in df.iterrows():
    color = celeste_uru if row['team_code'] == 'URU' else '#B0BEC5'
    if row['is_top5']:
        edge = '#FFD700'
        lw = 2.4
    elif row['is_valverde']:
        edge = '#FFD700'
        lw = 1.5
    else:
        edge = 'white'
        lw = 1.2
    ax.scatter(row['dp_per90'], row['int_per90'],
               s=row['circle_size'], color=color, edgecolor=edge,
               alpha=0.85, linewidth=lw)

# Etiquetas top 5%
for _, row in df[df['is_top5']].iterrows():
    label = f"{row['player_name']} ({row['team_code']})"
    ax.text(row['dp_per90'] + 0.05, row['int_per90'], label,
            fontsize=10, weight='bold', color='#212121')

# === LEYENDA EN ESQUINA INFERIOR DERECHA ===
# Círculos verticales entre x=5.4 y x=5.6, y descendente de 0.6
steps = 3
circle_spacing = 0.18
x_pos = df['dp_per90'].max() - 1.0
y_start = 0.6

for i, val in enumerate(np.linspace(df['kpi_weighted'].max(), df['kpi_weighted'].min(), steps)):
    s = ((val - df['kpi_weighted'].min()) /
         (df['kpi_weighted'].max() - df['kpi_weighted'].min())) * (max_size - min_size) + min_size
    y = y_start - i * circle_spacing
    label = "Higher KPI" if i == 0 else "Lower KPI" if i == steps - 1 else ""
    ax.scatter(x_pos, y, s=s, facecolors='none', edgecolors='gray', linewidth=1, zorder=3)
    if label:
        ax.text(x_pos + 0.3, y, label, fontsize=9, color='gray', va='center')

# Ejes y estética
ax.set_xlabel('Danger passes per 90 min (xG ≥ 0.07)', labelpad=12)
ax.set_ylabel('Interceptions per 90 min', labelpad=12)
ax.set_title('Weighted KPI – Midfielders, Copa América 2024', pad=15, fontsize=16, weight='bold')
ax.grid(True, linestyle='--', alpha=0.25)

# Límites balanceados
ax.set_xlim(0, df['dp_per90'].max() + 0.5)
ax.set_ylim(0, df['int_per90'].max() + 0.6)

plt.tight_layout()
plt.savefig("weighted_kpi_midfielders_copa2024.png", dpi=300, bbox_inches='tight', facecolor='white')
plt.show()



# BARCHART: TOP 10 con celeste actualizado para URU
top10 = df.sort_values(by='kpi_weighted', ascending=False).head(10).copy()
top10['label'] = top10['player_name'] + ' (' + top10['team_code'] + ')'
top10['color'] = top10['team_code'].apply(lambda x: '#78B7E5' if x == 'URU' else '#B0BEC5')

fig, ax = plt.subplots(figsize=(14, 7))
bars = ax.barh(top10['label'], top10['kpi_weighted'],
               color=top10['color'], edgecolor='white', height=0.6)

for i, (value, label) in enumerate(zip(top10['kpi_weighted'], top10['label'])):
    ax.text(value + 0.05, i, f'{value:.2f}', va='center', fontsize=10, color='#212121')

ax.invert_yaxis()
ax.set_xlabel('Weighted KPI (danger passes & interceptions per 90 min adjusted)', labelpad=10)
ax.set_title('Top 10 Midfielders by Weighted KPI – Copa América 2024', pad=15, fontsize=16, weight='bold')
ax.set_xlim(0, top10['kpi_weighted'].max() + 0.5)
ax.tick_params(axis='y', labelsize=11)
ax.tick_params(axis='x', labelsize=10)
ax.grid(axis='x', linestyle='--', alpha=0.3)

plt.tight_layout()
plt.savefig("top10_weighted_kpi_midfielders_copa2024.png", dpi=300, bbox_inches='tight', facecolor='white')
plt.show()

