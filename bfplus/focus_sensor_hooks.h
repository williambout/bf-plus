/* BF 1.04 exact native calls; one island shared with the scoped SPT fill.
 * Define A64_BRANCH(source,target,link) and u64 in the installer as for the
 * existing UI hook macros. Save the expanded tuples in immutable manifests. */
#ifndef BF_FOCUS_SENSOR_HOOKS_H
#define BF_FOCUS_SENSOR_HOOKS_H
#define FOCUS_SENSOR_ISLAND 0x4d3321190ULL
#define FOCUS_SENSOR_ISLAND_OLD ((u64)A64_BRANCH(FOCUS_SENSOR_ISLAND,0x4d33184c0ULL,0))
#define FOCUS_SENSOR_CALLS(X) \
 X(0x4d32ca044ULL,A64_BRANCH(0x4d32ca044ULL,0x4d3008200ULL,1)) \
 X(0x4d32ca054ULL,A64_BRANCH(0x4d32ca054ULL,0x4d3008200ULL,1)) \
 X(0x4d32bf008ULL,A64_BRANCH(0x4d32bf008ULL,0x4d32cb880ULL,1)) \
 X(0x4d32bf194ULL,A64_BRANCH(0x4d32bf194ULL,0x4d3033810ULL,1)) \
 X(0x4d32bf1bcULL,A64_BRANCH(0x4d32bf1bcULL,0x4d3033810ULL,1)) \
 X(0x4d32ca268ULL,A64_BRANCH(0x4d32ca268ULL,0x4d32cab80ULL,1)) \
 X(0x4d32bf1e0ULL,A64_BRANCH(0x4d32bf1e0ULL,0x4d32c9d20ULL,1))
#endif
