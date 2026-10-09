export type CategoryRow={categoryId:string;categoryName:string;parentId:string;sortOrder:number;description:string;status:number;version?:string;articleCount?:number;migratedTo?:string|null}
export type CategoryTree=CategoryRow & {children?:CategoryRow[]}
export function categoryOptions(rows:CategoryTree[]):CategoryRow[]{
  return rows.flatMap(row=>[row,...(row.children || []).filter(child=>!!child.categoryId).map(child=>({...child,categoryName:`${row.categoryName} / ${child.categoryName}`}))])
}
