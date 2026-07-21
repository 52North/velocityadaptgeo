Generate areas that can be reached from a chosen starting location within one or more travel-time limits using a combination of walking, cycling, and public transportation. The calculation should consider the selected departure time and scheduled transit services, returning reachable areas (isochrones) and the transit stops that can be accessed within each travel-time threshold.

--> multimodal isochrone is being selected

Find the easiest route between two points, avoiding steep slopes and difficult terrain, and taking into account that some directions are harder to travel than others (like walking uphill versus downhill). Some areas should be treated as no-go zones. Give me the resulting path and how much total effort it takes to follow it.

--> least cost path routing is being selected

Estimate values for something like air quality or soil moisture at places and times where there are no sensors, based on scattered readings from the sensors that do exist. Show the best-guess estimate along with how confident we should be in it.

--> bayesian spatiotemporal kriging is being selected

Figure out which locations are the best fit for a project by combining several maps of different criteria, letting me say how important each criterion is compared to the others, and combining them into one suitability score for every location.

--> multicriteria suitability overlay is being selected

Given a terrain elevation map and one or more outlet points, work out which area of land drains into each outlet, and trace out the streams and rivers within that drainage area.

--> watershed delineation is being selected

Look at the tracked positions of moving objects over time, like ships or vehicles, and flag anything unusual, such as stopping in odd places, sudden direction changes, or meeting up with something it doesn't normally interact with.

--> trajectory anomaly detection is being selected

Check a set of land parcel boundaries for problems like gaps, overlaps, or edges that don't line up with the neighboring parcels. List everything that's wrong, and optionally fix the boundaries automatically without changing the parcel sizes too much.

--> parcel topology validation is being selected

Combine a sharp black-and-white satellite image with a blurrier color image of the same area to produce one sharp color image, making sure the colors stay consistent and correct.

--> raster pansharpening is being selected

Take a 3D point cloud from a laser scan and separate the ground points from everything else, then label the remaining points as trees, buildings, water, or bare earth, and build a terrain model from the ground points.

--> pointcloud ground segmentation is being selected

From one or more observer locations, work out which parts of the landscape can actually be seen, taking into account the curve of the earth, the bending of light through the atmosphere, and anything like trees or buildings that might block the view.

--> viewshed line of sight is being selected
