"""Per-city season shift, in months, against New York's calendar (the one CW_TREE_SEASON and season.json are
written in): spring (leaf-out, pollen, bloom) and fall (color). Negative = earlier. Typical-year figures from
latitude, elevation and climate (USDA zone / first-frost dates, regional fall-color peak reports), rounded to
tenths of a month. A city's real season is THE SPECIES' NYC TIME + its shift.

Minneapolis peaks around early October, three to four weeks before New York; Atlanta and Dallas a week to two
after; coastal Southern California's street trees (sweetgum, Chinese pistache, ginkgo) color in late November
into December. Honolulu has no fall: fall is None and the page should say nothing seasonal about color there.
"""
SHIFT = {
    # north, continental
    'minneapolis': (0.7, -0.8), 'madison': (0.6, -0.6), 'milwaukee': (0.6, -0.5), 'siouxfalls': (0.7, -0.8),
    'desmoines': (0.3, -0.4),
    # Great Lakes
    'buffalo': (0.5, -0.4), 'rochester': (0.5, -0.4), 'detroit': (0.3, -0.3), 'grandrapids': (0.5, -0.5),
    # Rockies and the high desert
    'denver': (0.2, -0.6), 'auroraco': (0.2, -0.6), 'coloradosprings': (0.3, -0.6), 'albuquerque': (-0.3, -0.3),
    # the Northeast and mid-Atlantic, close to New York
    'providence': (0.2, -0.2), 'worcester': (0.4, -0.4), 'boston': (0.2, -0.2), 'pittsburgh': (0.1, -0.2),
    'columbus': (0.0, -0.2), 'indianapolis': (0.0, -0.2), 'baltimore': (-0.2, 0.0), 'washingtondc': (-0.3, 0.1),
    'jerseycity': (0.0, 0.0),
    # the middle South and lower Midwest
    'stlouis': (-0.3, 0.0), 'louisville': (-0.3, 0.0), 'overlandpark': (-0.2, -0.1), 'oklahomacity': (-0.6, 0.1),
    'knoxville': (-0.5, 0.1), 'nashville': (-0.6, 0.1), 'durham': (-0.6, 0.1), 'greensboro': (-0.5, 0.1),
    'richmond': (-0.4, 0.1),
    # the Deep South, Texas, Florida
    'atlanta': (-0.8, 0.3), 'arlington': (-1.0, 0.4), 'dallas': (-1.0, 0.4), 'plano': (-1.0, 0.4),
    'austin': (-1.3, 0.5), 'houston': (-1.5, 0.6), 'neworleans': (-1.6, 0.7), 'tampa': (-1.8, 0.7),
    'orlando': (-1.9, 0.8), 'capecoral': (-2.0, 0.8), 'miami': (-2.3, 0.9),
    # the desert Southwest
    'lasvegas': (-1.3, 0.6), 'phoenix': (-1.6, 0.8),
    # California
    'losangeles': (-1.5, 0.8), 'sandiego': (-1.5, 0.8), 'anaheim': (-1.5, 0.8), 'gardengrove': (-1.5, 0.8),
    'huntingtonbeach': (-1.5, 0.8), 'irvine': (-1.5, 0.8), 'ontario': (-1.3, 0.7), 'ranchocucamonga': (-1.3, 0.7),
    'sanfrancisco': (-1.2, 0.6), 'oakland': (-1.2, 0.6), 'sanjose': (-1.2, 0.6), 'santarosa': (-1.0, 0.4),
    'sacramento': (-1.0, 0.5), 'stockton': (-1.0, 0.5), 'fresno': (-1.1, 0.5),
    # the Pacific Northwest: an early, mild spring; fall about New York's
    'portland': (-0.6, 0.0), 'seattle': (-0.5, 0.0),
    # the tropics
    'honolulu': (-2.5, None),
}
