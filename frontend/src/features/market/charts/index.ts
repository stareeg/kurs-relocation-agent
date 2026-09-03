/**
 * Market chart primitives: pure SVG, `--status-*` / `--series-*` palettes, no charting libs.
 *
 * Каждый график — пара «геометрия (чистая функция, тестируется) + компонент (только разметка)».
 */
export { AgeBars } from "./AgeBars"
export type {
  AgeBarsBucket,
  AgeBarsRow,
  AgeBarsRowLayout,
  AgeBarsSegmentLayout,
  AgeBucketKey,
} from "./age-bars-geometry"
export { AGE_BUCKET_KEYS, AGE_BUCKET_LABELS, ageBarsRows } from "./age-bars-geometry"
export { CategoryBars } from "./CategoryBars"
export type { BarClassName } from "./CategoryBars"
export type {
  CategoryBar,
  CategoryBarsInput,
  CategoryBarLayout,
  CategoryBarsLayout,
  CategoryYTick,
} from "./category-bars-geometry"
export {
  CATEGORY_BARS_VALUE_LABEL_HEIGHT,
  CATEGORY_BARS_X_AXIS_HEIGHT,
  CATEGORY_BARS_Y_AXIS_WIDTH,
  categoryBarsLayout,
} from "./category-bars-geometry"
export { ChartTooltip } from "./ChartTooltip"
export type { ChartTooltipRow } from "./ChartTooltip"
export type {
  InterpolatedPosition,
  NearestCoord,
  UseInterpolatedHoverResult,
  UseNearestResult,
} from "./chart-hover"
export {
  interpolatedPosition,
  lerp,
  nearestIndex,
  useInterpolatedHover,
  useNearest,
} from "./chart-hover"
export { LineChart } from "./LineChart"
export type { LineChartInput, LineCoord, LineMetricInput, LinePoint } from "./line-chart-geometry"
export { formatDayShort, lineChartLayout } from "./line-chart-geometry"
export type {
  LineMetricLayout,
  LineXTick,
  LineYDomain,
  LineYTick,
  LineChartLayout,
} from "./line-chart-geometry"
export {
  LINE_CHART_HEADER_HEIGHT,
  LINE_CHART_PAD_BOTTOM,
  LINE_CHART_PAD_TOP,
  LINE_CHART_X_AXIS_HEIGHT,
  LINE_CHART_Y_AXIS_WIDTH,
} from "./line-chart-geometry"
export { SalaryDistribution } from "./SalaryDistribution"
export type {
  SalaryBar,
  SalaryBucket,
  SalaryDistributionInput,
  SalaryDomain,
  SalaryMedianMarker,
  SalaryOfferMarker,
  SalaryQuartileTick,
  SalaryTargetBracket,
} from "./salary-distribution-geometry"
export {
  MIN_HISTOGRAM_POINTS,
  SALARY_BUCKET_COUNT,
  formatMoneyFull,
  formatSalaryShort,
  salaryBuckets,
  salaryDistributionLayout,
} from "./salary-distribution-geometry"
export { seriesClass, seriesSlot, SERIES_SLOT_COUNT } from "./series-tokens"
export { Sparkline } from "./Sparkline"
export type { SparklineCoord, SparklinePoint } from "./sparkline-geometry"
export { sparklineLayout } from "./sparkline-geometry"
